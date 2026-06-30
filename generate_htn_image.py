import re
from graphviz import Digraph
import networkx as nx

def parse_plan_render(plan_text: str) -> Digraph:
    lines = plan_text.strip().splitlines()
    data = {}
    order = None
    warnings = []

    dot = Digraph("HTN")
    dot.attr(overlap='false')
    dot.attr(splines='true')
    dot.attr(dpi='300')
    dot.attr(size='10,5')

    for i, line in enumerate(lines):
        l = line.strip()
        if not l:
            continue

        action_match = re.match(r"^(\d+)\s+([\w\s()\-]+)$", l)
        method_match = re.match(r"^(\d+)\s+([\w\s()\-]+?)\s+->\s+([\w\-]+)\s*([\d\s]*)$", l)
        root_match = re.match(r"^root\s*([\d\s]*)$", l)
        step_count = 0
        if action_match:
            step_count += 1
            idx, label = action_match.groups()
            label = str(step_count) + ". " + label.strip()
            print("label:", label)
            data[idx] = (f'{idx}', label, 'box3d', [])
        elif method_match:
            idx, task, method, children = method_match.groups()
            child_list = children.strip().split() if children.strip() else []
            data[idx] = (f'{idx}', task, 'box', child_list)
            data[f"m{idx}"] = (f"m{idx}", method, 'ellipse', [])
        elif root_match:
            order = root_match.group(1).strip().split()
        else:
            warnings.append(f"Ignoring line {i+1}: {l}")

    if order is None:
        raise ValueError("Expected root")

    dot.node("root", shape="point")
    for o in order:
        dot.edge("root", o)

    queue = list(order)
    visited = set()
    # print(f"Queue: {queue}")

    while queue:
        current = queue.pop(0)
        # print(f"Current: {current}")
        if current in visited or current not in data:
            continue
        visited.add(current)

        node_id, label, shape, children = data[current]
        dot.node(node_id, label=label, shape=shape)

        for child in children:
            # dot.edge(node_id, child)
            queue.append(child)

        # If it's a method, add a separate node and edge to show method decomposition
        if current in data and current.startswith("m"):
            continue
        if f"m{current}" in data:
            method_id, method_label, _, _ = data[f"m{current}"]
            dot.node(method_id, label=method_label)
            dot.edge(current, method_id)
            for child in data[current][3]:
                dot.edge(method_id, child)
    # print("graph created", dot.source)
    return dot

def parse_plan(plan_text: str) -> nx.DiGraph:
    """
    Parses a plan text and constructs a NetworkX directed graph (nx.DiGraph).

    Args:
        plan_text (str): The plan text to parse.

    Returns:
        nx.DiGraph: A directed graph representing the HTN.
    """
    lines = plan_text.strip().splitlines()
    data = {}
    order = None
    warnings = []

    # Create a NetworkX directed graph
    graph = nx.DiGraph()
    step_count = 0
    for i, line in enumerate(lines):
        l = line.strip()
        if not l:
            continue

        action_match = re.match(r"^(\d+)\s+([\w\s()\-]+)$", l)
        method_match = re.match(r"^(\d+)\s+([\w\s()\-]+?)\s+->\s+([\w\-]+)\s*([\d\s]*)$", l)
        root_match = re.match(r"^root\s*([\d\s]*)$", l)
        
        if action_match:
            step_count += 1
            idx, label = action_match.groups()
            label = str(step_count) + ". " + label.strip()
            # print("label:", label)
            data[idx] = (f'{idx}', label, 'action', [], step_count)
        elif method_match:
            idx, task, method, children = method_match.groups()
            child_list = children.strip().split() if children.strip() else []
            data[idx] = (f'{idx}', task, 'task', child_list, 0)
            data[f"m{idx}"] = (f"m{idx}", method, 'method', [], 0)
        elif root_match:
            order = root_match.group(1).strip().split()
        else:
            warnings.append(f"Ignoring line {i+1}: {l}")

    if order is None:
        raise ValueError("Expected root")

    # Add the root node
    graph.add_node("root", label="root", shape="point", type="root", step=0)

    # Add edges from root to the initial tasks/methods
    for o in order:
        graph.add_edge("root", o)

    queue = list(order)
    visited = set()

    while queue:
        current = queue.pop(0)
        if current in visited or current not in data:
            continue
        visited.add(current)

        node_id, label, node_type, children, step = data[current]
        graph.add_node(node_id, label=label, type=node_type, step=step)

        for child in children:
            # graph.add_edge(node_id, child)
            queue.append(child)

        # If it's a method, add a separate node and edge to show method decomposition
        if current.startswith("m"):
            continue
        if f"m{current}" in data:
            method_id, method_label, _, _, step= data[f"m{current}"]
            graph.add_node(method_id, label=method_label, type="method", step=step)
            # print(f"Adding edge from {current} to method {method_id}")
            graph.add_edge(current, method_id)
            for child in data[current][3]:
                graph.add_edge(method_id, child)

    # Assign step values to tasks and methods based on the maximum step of their linked actions
    for node in reversed(list(nx.topological_sort(graph))):  # Process nodes in reverse topological order
        if graph.nodes[node]['type'] in {'task', 'method'}:
            max_step = graph.nodes[node].get('step', 0)
            for _, child in graph.out_edges(node):
                max_step = max(max_step, graph.nodes[child].get('step', 0))
            graph.nodes[node]['step'] = max_step
            # graph.nodes[node]['label'] += f" (Step: {max_step})"
    

    # Print warnings if any
    if warnings:
        print("\n".join(warnings))

    return graph

def parse_panda_output_filtered(text: str) -> nx.DiGraph:
    """
    Parse PANDA solver output into a filtered NetworkX DiGraph.

    Keeps:
      - abstract/decomposition nodes (e.g. t-wait-cooking[...] , cook[...] , __top[])
      - primitive action nodes (e.g. a-interact[...] , wait[...] , none[...] )

    Filters out:
      - __method_precondition_* nodes

    Edges:
      - decomposition edges from abstract task -> child
      - root -> 0 for the top node

    Node attributes:
      - label
      - kind: {'abstract', 'primitive', 'root'}
      - chosen_method (for decomposition nodes when available)
      - raw_line
    """
    G = nx.DiGraph()
    G.add_node("root", label="root", kind="root")

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    numbered_line_re = re.compile(r"^(\d+)\s+(.*)$")
    decomp_re = re.compile(r"^(\d+)\s+(.+?)\s*->\s*(.+)$")

    # Store line info first
    line_info = {}        # node_id -> content
    decomposition_info = {}  # node_id -> (lhs, rhs)

    for line in lines:
        m = numbered_line_re.match(line)
        if not m:
            continue
        node_id = int(m.group(1))
        content = m.group(2)
        line_info[node_id] = content

        dm = decomp_re.match(line)
        if dm:
            lhs = dm.group(2).strip()
            rhs = dm.group(3).strip()
            decomposition_info[node_id] = (lhs, rhs)

    def is_filtered_label(label: str) -> bool:
        return label.startswith("__method_precondition_")

    def classify_node(label: str, is_decomposition: bool) -> str:
        if is_decomposition:
            return "abstract"
        return "primitive"

    # Pass 1: add kept nodes
    for node_id, content in line_info.items():
        if is_filtered_label(content):
            continue

        is_decomposition = node_id in decomposition_info
        if is_decomposition:
            label = decomposition_info[node_id][0]
        else:
            label = content

        G.add_node(
            node_id,
            label=label,
            raw_line=content,
            kind=classify_node(label, is_decomposition),
        )

    # Pass 2: add decomposition edges
    for parent_id, (lhs, rhs) in decomposition_info.items():
        if parent_id not in G:
            continue

        tokens = rhs.split()
        if tokens:
            G.nodes[parent_id]["chosen_method"] = tokens[0]

        # Special handling for top node
        if lhs == "__top[]":
            G.add_edge("root", parent_id, relation="root")
            G.nodes[parent_id]["rhs_raw"] = rhs

        # Add only children that were kept
        child_ids = [int(x) for x in re.findall(r"\b\d+\b", rhs)]
        for child_id in child_ids:
            if child_id == parent_id:
                continue
            if child_id in G:
                G.add_edge(parent_id, child_id, relation="decomposes_to")

    return G


def pretty_print_graph(G: nx.DiGraph) -> None:
    print("Nodes:")
    for n, data in G.nodes(data=True):
        print(
            f"  {n}: "
            f"label={data.get('label')} | "
            f"kind={data.get('kind')} | "
            f"method={data.get('chosen_method', '')}"
        )

    print("\nEdges:")
    for u, v, data in G.edges(data=True):
        print(f"  {u} -> {v} ({data.get('relation', '')})")


# Optional: cleaner version that also removes split-helper abstract nodes
def prune_split_nodes(G: nx.DiGraph) -> nx.DiGraph:
    """
    Remove nodes whose labels/methods are compilation artifacts like:
      - m-..._splitted_...
      - _splitting_method_...

    Reconnect parent(s) directly to child(ren).
    """
    H = G.copy()

    def is_split_artifact(node_data: dict) -> bool:
        label = str(node_data.get("label", ""))
        method = str(node_data.get("chosen_method", ""))
        return (
            "_splitted_" in label
            or label.startswith("m-") and "_splitted_" in label
            or method.startswith("_splitting_method_")
        )

    changed = True
    while changed:
        changed = False
        for n in list(H.nodes()):
            if n == "root":
                continue
            if n not in H:
                continue

            data = H.nodes[n]
            if not is_split_artifact(data):
                continue

            preds = list(H.predecessors(n))
            succs = list(H.successors(n))

            for p in preds:
                for s in succs:
                    if p != s:
                        H.add_edge(p, s, relation="decomposes_to")

            H.remove_node(n)
            changed = True
            break

    return H


def render_nx_plan_graph(graph: nx.DiGraph, name: str = "HTN") -> Digraph:
    dot = Digraph(name)
    dot.attr(overlap='false')
    dot.attr(splines='true')
    dot.attr(dpi='300')
    dot.attr(size='10,5')

    shape_map = {
        'root': 'point',
        'task': 'box',
        'method': 'ellipse',
        'action': 'box3d',
    }

    for node_id, attrs in graph.nodes(data=True):
        node_type = attrs.get('type', 'task')
        label = attrs.get('label', str(node_id))
        shape = shape_map.get(node_type, 'box')
        dot.node(str(node_id), label=str(label), shape=shape)

    for source, target in graph.edges():
        dot.edge(str(source), str(target))

    return dot


# Example usage
if __name__ == "__main__":
    with open("test_plan_panda.txt", "r") as f:
        plan_content = f.read()

    match = re.search(r"==>\n([^<]*)", plan_content, re.DOTALL)
    input_text = match.group(1).strip() if match else plan_content

    nx_graph = parse_panda_output_filtered(input_text)
    pretty_print_graph(nx_graph)
    dot_graph = render_nx_plan_graph(nx_graph, name="HTN_PANDA")
    dot_graph.render("htn_plan", format="png", cleanup=True)
    print("Saved as htn_plan.png")
