from src.llm.client import LLMClient
from dotenv import load_dotenv

load_dotenv()
client = LLMClient()
print("Healthy:", client.is_healthy())
print("Model:", client.model)

print("\n--- Test Generation ---")
response = client.generate("Hello, are you a Llama model? Please reply in one sentence.", system="You are a helpful AI.")
print(response)

print("\n--- Test JSON Generation ---")
json_resp = client.generate_json("Output a JSON object with keys 'status' and 'model' and their string values.", system="Always output valid JSON.")
print(json_resp)
