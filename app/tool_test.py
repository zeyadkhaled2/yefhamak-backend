
"""Does your model support tool calling? Run from the project root:
 
    python -m app.tool_test
 
Expected: the first message makes the model CALL the search tool, the second (a greeting) gets a normal TEXT reply.
"""
from openai import OpenAI
 
from app.config import settings
 
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search the shop's catalog for the product the customer is asking about.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What the customer asked for, in their own words"}
                },
                "required": ["query"],
            },
        },
    }
]
 
SYSTEM = (
    "You are the order assistant for a small Egyptian clothing shop. "
    "Never state products, prices or stock from memory: use the search_products tool for any product question. "
    "For greetings, just reply briefly in Egyptian Arabic."
)
 
MESSAGES = ["عندكم الهودي البني مقاس M؟ وبكام؟", "صباح الخير"]
 
 
def main() -> None:
    if not settings.openrouter_api_key:
        print("OPENROUTER_API_KEY is missing in .env")
        return
 
    client = OpenAI(api_key=settings.openrouter_api_key, base_url="https://openrouter.ai/api/v1")
    print("Model:", settings.llm_model, "\n")
 
    for text in MESSAGES:
        print("CUSTOMER:", text)
        try:
            response = client.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}],
                tools=TOOLS,
                temperature=0,
                max_tokens=600,
            )
        except Exception as e:
            print("ERROR:", str(e)[:300])
            print("-> This model may not support tool calling. Tell me this message.")
            return
 
        message = response.choices[0].message
        if message.tool_calls:
            for call in message.tool_calls:
                print("TOOL CALL:", call.function.name, call.function.arguments)
        else:
            print("TEXT REPLY:", (message.content or "(empty)")[:200])
        print("-" * 40)
 
 
if __name__ == "__main__":
    main()

