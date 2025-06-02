from dotenv import load_dotenv
from openai import OpenAI
import tiktoken

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def load_txt_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()

def split_lines(file_string):
    return [line.strip() for line in file_string.splitlines() if line.strip()]

def get_user_query():
    return input("\n❓ What part of the process have you already done? Write it here: \n  ").strip()

def gpt_scoring(system_prompt, file_text, user_question, options,
                model="gpt-4o", top_logprobs=5):
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": file_text},
        {"role": "user",   "content": user_question}
    ]
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.3,
        max_tokens=64,
        logprobs=True,
        top_logprobs=top_logprobs
    )
    logp = resp.choices[0].logprobs
    encoding = tiktoken.encoding_for_model(model)

    # build list of maps: for each output token, its top_logprobs
    top_logp_list = [
        {t.token: t.logprob for t in tok.top_logprobs}
        for tok in logp.content
    ]

    # score each option
    scores = {}
    for opt in options:
        total = 0
        for i, tid in enumerate(encoding.encode(opt)):
            if i >= len(top_logp_list):
                break
            token = encoding.decode([tid])
            total += top_logp_list[i].get(token, -100)
        scores[opt] = total

    # sort descending
    sorted_opts = sorted(scores.items(), key=lambda x: -x[1])
    return sorted_opts, resp.choices[0].message.content.strip()


# Load process plan and options
file_path = "C:\\Users\\krist\\OneDrive - Politecnico di Milano\\Desktop\\LLM\\es1_steel.txt"
file_content = load_txt_file(file_path)

opts_path = "C:\\Users\\krist\\OneDrive - Politecnico di Milano\\Desktop\\LLM\\options.txt"
options_list = split_lines(load_txt_file(opts_path))


system_prompt = (
    "You are a mechanical engineer. You are provided with a process plan for a CNC machine operation to follow carefully. "
    "The user will tell you what part of the process they have already completed. "
    "You will suggest the right next action to take choosing only from the provided options. Take the actions the user has already completed as the starting point and follow the process plan."
    "DO NOT ADD ACTIONS THAT ARE NOT IN THE AVAILABLE ONES."
    "Make sure all steps of an operation have been done before starting the CNC machine and going to the next operation. "
    "After waiting for the CNC machine to finish before beginning setting up the next stage you need to stop the CNC machine and turn off the coolant."
    "Mandatory: you must output one of the following options and nothing else, no bullet points, no dash, no additional characters.\n"
    "BEGIN OPTIONS AVAILABLES:\n"
    + "\n".join(f"- {o}" for o in options_list)
    + "\nEND OPTIONS."
)

# ——— First call ———
initial_user_query = "The user said: " + get_user_query()
scores, reply = gpt_scoring(system_prompt, file_content, initial_user_query, options_list)

print("----------------------------------------------------")
print("\n📌 GPT reply:\n" + reply)
print("\n📗 Top 5 scored options:")
for opt, sc in scores[:5]:
    print(f"{opt}: {sc:.2f}")

confirm = input("\nWould you like to continue? (y/N): ").strip().lower()
if confirm != 'y':
    print("Stopping—resume when you’re ready.")
    exit()

completed = [scores[0][0]]

# ——— Iterative loop ———
while True:
    done_str = "After that, also these actions were completed (in order):\n" + "\n".join(f"- {a}" for a in completed)
    user_query = initial_user_query + "\n" + done_str + "\nWhat’s the next action that should be done?"
    #print("\n📌 User query:\n" + user_query)
    scores, reply = gpt_scoring(system_prompt, file_content, user_query, options_list)
    print("----------------------------------------------------")
    print("\n📌 GPT replied the next action is:\n" + reply)
    print("\n📗 Top 5 scored options:")
    for opt, sc in scores[:5]:
        print(f"{opt}: {sc:.2f}")

    confirm = input("\nHave you finished this action? (y/N): ").strip().lower()
    if confirm != 'y':
        print("Stopping—you can pick up from here later.")
        break

    completed.append(scores[0][0])