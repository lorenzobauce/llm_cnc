# llm_cnc ⚙️🔩🔧 
LLM-Assisted Process Planning for CNC Machining

# Guide
1. Clone this repo.
```bash
git clone https://github.com/lorenzobauce/llm_cnc.git
```

2. Creating a new anaconda environment.
```bash
conda create -n llm_cnc python=3.10 -y
conda activate llm_cnc
bash install.sh
```
  You need to activate the environment each time you enter in it. In case you need to deactivate simply type:
```bash
conda deactivate

```
3. Copy the API key in a file called .env
```bash
OPENAI_API_KEY='copy your API key here'
```

4. Run the main program.
```python
python main.py
```


