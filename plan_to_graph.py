#!/usr/bin/env python3
"""
Convert pandaPIengine plan output to an HTN decomposition graph saved as PNG.

Usage:
    python3 plan_to_graph.py <plan_file> [output.png]
    ./pandaPIengine problem.sas | python3 plan_to_graph.py - [output.png]
"""

import os
import re
import subprocess
import sys
import tempfile

import networkx as nx


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_plan(text):
    """
    Extract primitive actions, decompositions, and root from pandaPIengine output.

    Returns:
        primitives    : dict  id -> action_name
        decompositions: dict  id -> (task_name, method_name, [child_ids])
        root          : int   id of the root task
    """
    match = re.search(r'==>(.*?)<==', text, re.DOTALL)
    if not match:
        raise ValueError("No plan section found between ==> and <==")

    primitives = {}
    decompositions = {}
    root = None

    for line in match.group(1).splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith('root '):
            root = int(line.split()[1])
            continue

        if ' -> ' in line:
            # Abstract task decomposition:
            #   <id> <task_name> -> <method_name> [child_id ...]
            left, right = line.split(' -> ', 1)
            id_str, task_name = left.split(' ', 1)
            tokens = right.split()
            method_name = tokens[0]
            children = [int(t) for t in tokens[1:]]
            decompositions[int(id_str)] = (task_name.strip(), method_name, children)
        else:
            # Primitive action:
            #   <id> <action_name>
            tokens = line.split(' ', 1)
            if len(tokens) == 2:
                primitives[int(tokens[0])] = tokens[1]

    if root is None:
        raise ValueError("No 'root' line found in plan")

    return primitives, decompositions, root


# ---------------------------------------------------------------------------
# DOT generation
# ---------------------------------------------------------------------------

def _dot_escape(s):
    """Escape a string for use inside a DOT double-quoted label."""
    return s.replace('\\', '\\\\').replace('"', '\\"')


def _task_label(raw):
    """
    Format a task or action label as two lines: name on top, params below.

    Input examples:
        'drive[truck-0,city-loc-2,city-loc-1]'
        'get-to[truck-0,city-loc-2]'
        '__top[]'
    """
    m = re.match(r'^([^\[]+)\[([^\]]*)\]$', raw.strip())
    if not m:
        return _dot_escape(raw)
    name, params = m.group(1), m.group(2)
    # Escape name and params independently, then join with DOT's \n (line break).
    # The \\n in the f-string produces a literal backslash-n in the DOT source,
    # which graphviz interprets as a centered line break.
    if params:
        return f"{_dot_escape(name)}\\n{_dot_escape(params)}"
    return _dot_escape(name)


def _parse_method(raw):
    """
    Return (dot_label, params) for a raw method string.

    Simple names like 'm-drive-to' return ('m-drive-to', []).

    Compound grounder-generated names encode a decomposition chain using
    semicolons inside angle brackets, e.g.:
        '<achieve-on-table-unstack;achieve-on-table-unstack_splitted_5[G];
          _splitting_method_achieve-on-table-unstack_splitted_5;0;-1,-2,1>'

    The chain is parsed token by token (split on ';'):
      - Pure-numeric tokens (e.g. '0', '-1,-2,1') are skipped — they are
        grounder-internal indices.
      - '_splitting_method_...' tokens are skipped — compilation artifacts.
      - '_splitted_N[params]' tokens are collapsed: their params are captured
        and returned, the token itself is discarded.
      - The first remaining token is the real method name.
    """
    s = raw.strip()
    if not s.startswith('<'):
        return _dot_escape(s), []

    # Strip all leading '<' and trailing '>'
    s = s.lstrip('<').rstrip('>')

    name = None
    params = []

    for token in s.split(';'):
        t = token.strip().rstrip('>')   # drop stray '>' from nested brackets
        if not t:
            continue
        # Pure numeric token: only digits, minus signs, commas
        if re.match(r'^[-\d,]+$', t):
            continue
        # Splitting-method artifact → discard entirely
        if '_splitting_method_' in t:
            continue
        # Splitted task → extract its parameters, discard the token itself
        if '_splitted_' in t:
            m = re.match(r'^[^\[]+\[([^\]]*)\]$', t)
            if m and m.group(1):
                params.append(m.group(1))
            continue
        # First surviving token is the real method name
        if name is None:
            name = t.lstrip('_').replace('splitting_method_', '') or t

    return _dot_escape(name or raw), params


def _is_precondition_action(nid, primitives):
    """True when nid is a synthetic __method_precondition_... action inserted by the parser."""
    return nid in primitives and primitives[nid].startswith('__method_precondition_')


def _is_splitting_artifact(nid, decompositions):
    """True when nid is a grounder-generated _splitted_ task / _splitting_method_ pair."""
    if nid not in decompositions:
        return False
    task, method, _ = decompositions[nid]
    return '_splitted_' in task and '_splitting_method_' in method


def _expand_children(children, decompositions):
    """
    Recursively replace any splitting-artifact child IDs with their own children.

    Returns:
        (real_children, split_params)
        real_children  — list of child IDs with splitting artifacts inlined
        split_params   — list of parameter strings extracted from the _splitted_
                         task names encountered during expansion, in order
    """
    real_children = []
    split_params = []
    for cid in children:
        if _is_splitting_artifact(cid, decompositions):
            task, _, grandchildren = decompositions[cid]
            # Pull the parameters out of 'base_splitted_N[p1,p2,...]'
            m = re.match(r'^[^\[]+\[([^\]]*)\]$', task.strip())
            if m and m.group(1):
                split_params.append(m.group(1))
            sub_children, sub_params = _expand_children(grandchildren, decompositions)
            real_children.extend(sub_children)
            split_params.extend(sub_params)
        else:
            real_children.append(cid)
    return real_children, split_params


def build_dot(primitives, decompositions, root):
    """Return a Graphviz DOT string for the HTN decomposition tree.

    The graph is built by BFS from 'root', following the child-ID lists
    on each decomposition line.  Only nodes reachable from root are emitted.
    Splitting artifacts (_splitted_ tasks and _splitting_method_ methods) are
    collapsed: their parent connects directly to their grandchildren.

    Structure per decomposition step:
        abstract-task-node  →  method-node  →  child-nodes ...
    """
    node_decls = []   # DOT node declaration lines
    edge_decls = []   # DOT edge declaration lines
    visited = set()

    queue = [root]
    while queue:
        nid = queue.pop(0)
        if nid in visited:
            continue
        visited.add(nid)

        if nid in decompositions:
            task, method, children = decompositions[nid]

            # Abstract task node
            if nid == root:
                node_decls.append(
                    f'  n{nid} [label="{_task_label(task)}", shape=diamond, '
                    f'style=filled, fillcolor=lightblue, fontsize=9];'
                )
            else:
                node_decls.append(
                    f'  n{nid} [label="{_task_label(task)}", shape=box, '
                    f'style="filled,rounded", fillcolor=lightblue, fontsize=9];'
                )

            # Collapse splitting artifacts; also separate out __method_precondition_
            # leaves and capture their parameters before discarding them.
            expanded, params_from_children = _expand_children(children, decompositions)
            prec_params = []
            real_children = []
            for cid in expanded:
                if _is_precondition_action(cid, primitives):
                    m = re.match(r'^[^\[]+\[([^\]]*)\]$', primitives[cid])
                    if m and m.group(1):
                        prec_params.append(m.group(1))
                else:
                    real_children.append(cid)

            # Build the method label.
            # Parameters come from up to three sources:
            #   1. _splitted_ nodes in the children list  (_expand_children)
            #   2. _splitted_ tokens embedded in the method name  (_parse_method)
            #   3. __method_precondition_ leaves
            # Source 3 replaces 1+2 when its parameter set is a superset of
            # theirs — meaning it carries strictly more information.
            method_label, params_from_name = _parse_method(method)
            all_params = params_from_children + params_from_name
            if prec_params:
                existing = {t.strip() for s in all_params for t in s.split(',')}
                prec     = {t.strip() for s in prec_params for t in s.split(',')}
                if prec >= existing:          # superset: use the richer set
                    all_params = prec_params
            for p in all_params:
                method_label += f"\\n{_dot_escape(p)}"

            # Method node (DOT id prefixed with "m" to stay distinct from task ids)
            node_decls.append(
                f'  m{nid} [label="{method_label}", shape=box, '
                f'style=filled, fillcolor=yellow, fontsize=9];'
            )

            # task → method, then method → each real child in order
            edge_decls.append(f'  n{nid} -> m{nid};')
            for child_id in real_children:
                edge_decls.append(f'  m{nid} -> n{child_id};')
                queue.append(child_id)

        elif nid in primitives:
            node_decls.append(
                f'  n{nid} [label="{_task_label(primitives[nid])}", shape=ellipse, '
                f'style=filled, fillcolor=lightgreen, fontsize=9];'
            )

        else:
            # Referenced by parent but absent from plan — mark clearly
            node_decls.append(
                f'  n{nid} [label="?{nid}", shape=ellipse, '
                f'style="filled,dashed", fillcolor=lightcoral, fontsize=9];'
            )

    lines = [
        'digraph HTN_Plan {',
        '  rankdir=TB;',
        '  ordering=out;',   # children laid out left-to-right in declaration order
        '  node [fontname="Helvetica", fontsize=10, margin="0.15,0.1"];',
        '  edge [color=gray50, arrowsize=0.8];',
        '',
        *node_decls,
        '',
        *edge_decls,
        '}',
    ]
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_dot(dot_source, output_path):
    """Call graphviz dot to render the DOT source to a PNG file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.dot', delete=False) as f:
        f.write(dot_source)
        dot_tmp = f.name
    try:
        result = subprocess.run(
            ['dot', '-Tpng', '-o', output_path, dot_tmp],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"graphviz dot failed:\n{result.stderr}")
    finally:
        os.unlink(dot_tmp)


# ---------------------------------------------------------------------------
# Cytoscape-compatible graph builder
# ---------------------------------------------------------------------------

def _panda_method_label(raw: str) -> str:
    """Extract a human-readable method name without DOT escaping."""
    s = raw.strip()
    if not s.startswith('<'):
        return s
    s = s.lstrip('<').rstrip('>')
    for token in s.split(';'):
        t = token.strip().rstrip('>')
        if not t:
            continue
        if re.match(r'^[-\d,]+$', t):
            continue
        if '_splitting_method_' in t or '_splitted_' in t:
            continue
        return t.lstrip('_') or t
    return s.split(';')[0].strip() if s else raw


def panda_plan_to_digraph(text: str) -> nx.DiGraph:
    """
    Convert pandaPIengine output into an nx.DiGraph whose node attributes
    match what digraph_to_cytoscape_elements() in app.py expects:
      - label (str)
      - type  : 'root' | 'task' | 'method' | 'action'
      - step  : int (sequential execution order; 0 for structural nodes)

    Filtering applied automatically:
      - __method_precondition_* primitives are dropped
      - _splitted_ / _splitting_method_ artifact nodes are inlined away
    """
    primitives, decompositions, root = parse_plan(text)

    graph = nx.DiGraph()
    graph.add_node("root", label="root", type="root", step=0)

    # Assign sequential steps to real (non-precondition) primitives sorted by id
    step_count = 0
    primitive_steps: dict = {}
    for pid in sorted(primitives.keys()):
        if not _is_precondition_action(pid, primitives):
            step_count += 1
            primitive_steps[pid] = step_count

    # Add primitive action nodes (label prefixed with step number, matching Lilotane style)
    for pid, action_name in primitives.items():
        if _is_precondition_action(pid, primitives):
            continue
        step = primitive_steps.get(pid, 0)
        graph.add_node(
            f"n{pid}",
            label=f"{step}. {action_name}",
            type="action",
            step=step,
        )

    # Add task + method nodes for each non-splitting decomposition
    for did, (task_name, method_name, children) in decompositions.items():
        if _is_splitting_artifact(did, decompositions):
            continue

        graph.add_node(f"n{did}", label=task_name, type="task", step=0)
        graph.add_node(f"m{did}", label=_panda_method_label(method_name), type="method", step=0)
        graph.add_edge(f"n{did}", f"m{did}")

        real_children, _ = _expand_children(children, decompositions)
        for child_id in real_children:
            if _is_precondition_action(child_id, primitives):
                continue
            graph.add_edge(f"m{did}", f"n{child_id}")

    # Synthetic root → root task
    graph.add_edge("root", f"n{root}")

    # Propagate step values upward: tasks/methods inherit max action step of descendants
    for node in reversed(list(nx.topological_sort(graph))):
        if graph.nodes[node].get('type') in {'task', 'method', 'root'}:
            max_step = graph.nodes[node].get('step', 0)
            for _, child in graph.out_edges(node):
                max_step = max(max_step, graph.nodes[child].get('step', 0))
            graph.nodes[node]['step'] = max_step

    return graph


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0)

    input_arg = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else 'plan_graph.png'

    if input_arg == '-':
        text = sys.stdin.read()
    else:
        with open(input_arg) as f:
            text = f.read()

    primitives, decompositions, root = parse_plan(text)
    print(f"Parsed: {len(primitives)} primitive actions, "
          f"{len(decompositions)} abstract tasks, root={root}")

    dot = build_dot(primitives, decompositions, root)
    render_dot(dot, output_path)
    print(f"Graph saved to: {output_path}")


if __name__ == '__main__':
    main()
