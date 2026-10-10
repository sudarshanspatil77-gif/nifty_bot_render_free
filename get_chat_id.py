
import requests, json, sys

print("=== TELEGRAM CHAT ID FINDER - SUDARSHAN ===")
print()

token = input("Tujha Bot Token paste kar (BotFather kadoon milala te): ").strip()
if not token:
    print("Token takla nahi!"); input(); sys.exit()

print("\nBot la Hi message pathavla ka? @tujha_bot la")
input("Pathavla asel tar ENTER dab...")

try:
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    print(f"\nChecking: {url}")
    r = requests.get(url, timeout=10)
    data = r.json()
    print("\nFull Response:")
    print(json.dumps(data, indent=2))
    
    if data.get("result"):
        for msg in data["result"]:
            chat = msg.get("message", {}).get("chat") or msg.get("my_chat_member", {}).get("chat")
            if chat:
                cid = chat.get("id")
                name = chat.get("first_name","")
                print(f"\n✅ CHAT ID MILALA: {cid} (Name: {name})")
                print(f"\nconfig.json madhe asa tak:")
                print(f'"telegram_chat_id": "{cid}"')
                break
        else:
            print("\n❌ Kahi message disat nahi")
            print("1. Tujhya bot la Telegram madhe search kar")
            print("2. START dabun 'Hi' pathav")
            print("3. Parat ha script chalav")
    else:
        print("No result - Bot la message pathavla ka?")
        
except Exception as e:
    print(f"Error: {e}")

input("\nENTER dabun band kar...")
