import os
import dotenv
dotenv.load_dotenv()

# LLM 配置
_configs= {"LLM_BASE_URL": os.getenv("LLM_BASE_URL"),
           "LLM_API_KEY": os.getenv("LLM_API_KEY"),
           "LLM_MODEL": os.getenv("LLM_MODEL"),
           "NOTE_ROOT_PATH": os.getenv("NOTE_ROOT_PATH")}


def get_value(key:str):
    return _configs.get(key, "None")

def reset_agent_log():
    pass

def load_config():
    dotenv.load_dotenv()

def save_model_config(model:str,api_key:str,base_url:str,note_path:str):
    global _configs
    _configs["LLM_MODEL"] = model
    _configs["LLM_API_KEY"] = api_key
    _configs["LLM_BASE_URL"] = base_url
    _configs["NOTE_ROOT_PATH"] = note_path
    _save_config()


def _save_config():
    print(_configs)
    path = os.path.abspath(os.path.join(__file__, '..', '.env'))
    if os.path.exists(path):
        f = open(path, "w")
        with f:
            f.write(f"LLM_BASE_URL={_configs["LLM_BASE_URL"]}\n")
            f.write(f"LLM_API_KEY={_configs["LLM_API_KEY"]}\n")
            f.write(f"LLM_MODEL={_configs["LLM_MODEL"]}\n")
            f.write(f"NOTE_ROOT_PATH={_configs["NOTE_ROOT_PATH"]}\n")
            print(f"name===={f.name}")