"""Builds game_event_agent_colab.ipynb. Run: python make_notebook.py"""

import json

cells = []


def md(text):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": text.strip()})


def code(text):
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": text.strip()})


md("""
# Game Event Planning Agent
CSYE 7374 mini project. The agent reads results from two fictional past events and player comments,
chooses which data to inspect, and proposes the next event format as a **draft for human approval**.
It never publishes anything.

**Setup:** Runtime → Change runtime type → **T4 GPU**. Run the cells in order.
""")

md("## 1. Install and start Ollama, download Qwen3 8B (takes a few minutes)")
code("""
!apt-get -qq install -y zstd > /dev/null
!curl -fsSL https://ollama.com/install.sh | sh
""")
code("""
import subprocess, time, requests
subprocess.Popen(['ollama', 'serve'], stdout=open('ollama.log', 'w'), stderr=subprocess.STDOUT)
for _ in range(30):
    try:
        if requests.get('http://127.0.0.1:11434/api/tags', timeout=2).status_code == 200:
            print('Ollama server is running'); break
    except requests.RequestException:
        time.sleep(1)
""")
code("""
!ollama pull qwen3:8b
""")

md("""
## 2. Get the project files
Option A: upload `game_event_agent.zip` (the cell below opens a file picker).
Option B: if the project is on GitHub, replace the upload cell with `!git clone <your repo url> game_event_agent`.
""")
code("""
from google.colab import files
import zipfile, os
uploaded = files.upload()                       # choose game_event_agent.zip
zipfile.ZipFile(next(iter(uploaded))).extractall('/content')
os.chdir('/content/game_event_agent')
print(os.listdir('.'))
""")

md("## 3. Offline tests (no model needed): tool numbers and loop rules")
code("""
!python tests/test_agent.py
""")

md("## 4. Look at the data the agent can access")
code("""
import json, sys
sys.path.insert(0, '.')
from tools import Toolbox
tb = Toolbox()
print(json.dumps(tb.compare_events('participation_rate'), indent=2))
print(json.dumps(tb.compare_events('revenue_per_day_change'), indent=2))
""")

md("""
## 5. Case 1: goal = increase revenue
When the draft appears, read it and type **APPROVE** or **REJECT**. Approval does not publish anything.
""")
code("""
from agent import OllamaModel
from run_demos import run_case, comparison_table
model = OllamaModel()     # qwen3:8b, temperature 0
runs = {}
runs['1'] = run_case('1_increase_revenue', model)
""")

md("## 6. Case 2: goal = increase player participation")
code("""
runs['2'] = run_case('2_increase_participation', model)
""")

md("## 7. Compare the two recommendations")
code("""
from IPython.display import Markdown
table = comparison_table(runs['1'], runs['2'])
open('runs/goal_comparison.md', 'w').write('# Same data, two goals\\n\\n' + table + '\\n')
Markdown(table)
""")

md("## 8. Case 3: missing information (the data has no install or acquisition figures)")
code("""
runs['3'] = run_case('3_missing_install_data', model)
""")

md("## 9. Case 4: invalid request (event E3 does not exist, and the user asks to publish)")
code("""
runs['4'] = run_case('4_invalid_request', model)
""")

md("## 10. Show one full trace and download all records")
code("""
print(open('runs/1_increase_revenue.md').read())
""")
code("""
!zip -qr runs.zip runs
files.download('runs.zip')
""")

nb = {"cells": cells, "metadata": {"accelerator": "GPU", "colab": {"provenance": []},
                                   "kernelspec": {"name": "python3", "display_name": "Python 3"}},
      "nbformat": 4, "nbformat_minor": 0}
with open("game_event_agent_colab.ipynb", "w", encoding="utf-8") as f:
    json.dump(nb, f, indent=1)
print("wrote game_event_agent_colab.ipynb with", len(cells), "cells")
