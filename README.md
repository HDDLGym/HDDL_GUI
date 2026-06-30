#HDDL-GUI


HDDL-GUI is the graphical user interface to interactively visualize the hierarchical structures of the HDDL domains, problems, and resulting plans. It is also equipped with 2 HDDL solvers, [Lilotane](https://github.com/domschrei/lilotane) and [PANDA](https://github.com/panda-planner-dev). Graphical visualization design is inspired by the work [HTN Plan Viewer](https://github.com/Maumagnaguagno/HTN_Plan_Viewer).

To run the GUI, follow these steps:

1. Install the required packages by running this command on the terminal in the HDDL_GUI directory:

`pip install .`

2. \[Optional\] Add the Anthropic API key to the file *.env* if you wish to call LLM.

3. \[Optional\] The repo includes the solvers in executable binary files. If you wish to install the solver yourself, please follow the links above to get them from the original sources. Please save the solvers in similar name and location to ensure the GUI still work.

4. Call the app.py on the terminal by running this command:

`python app.py`

5. On the terminal, there will be an link to open the GUI in any browser. Copy that link and open with a browser (Chrome, Firefox, or others).

6. Please refer to this [youtube video](https://youtu.be/U-DlFmgnKA8) for instroduction and instruction to ultilize all features that the LLM-powered HDDL-GUI offers.


Authors: Ngoc La, Anthony Favier
