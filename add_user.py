import json
import hashlib
import secrets
import string
from pathlib import Path

USERS_FILE = Path(__file__).parent / "users.json"


def load_users():
    if not USERS_FILE.exists():
        return {}
    with USERS_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_users(users):
    with USERS_FILE.open("w", encoding="utf-8") as f:
        json.dump(users, f, indent=2, ensure_ascii=False)


def generate_key_string():
    """Generates a license key in the format: DUPES-XXXXXX-XXXXXX (letters & numbers)"""
    chars = string.ascii_letters + string.digits
    part1 = "".join(secrets.choice(chars) for _ in range(6))
    part2 = "".join(secrets.choice(chars) for _ in range(6))
    return f"DUPES-{part1}-{part2}"


def create_license_for_friend(friend_name):
    """Creates a unique license code and saves it for a user/friend."""
    key = generate_key_string()
    users = load_users()
    users[friend_name] = key
    save_users(users)
    return key


def add_manual_user(username, password):
    users = load_users()
    users[username] = password
    save_users(users)
    print(f"\n✅ User '{username}' successfully saved!")


def list_users():
    users = load_users()
    print("\n" + "=" * 50)
    print(f"{'USER / FRIEND':<22} | {'LICENSE KEY / PASSWORD'}")
    print("-" * 50)
    if not users:
        print("No users found.")
    for u, p in users.items():
        print(f"{u:<22} | {p}")
    print("=" * 50 + "\n")


def export_json():
    users = load_users()
    print("\n" + "=" * 50)
    print("🌐 JSON FOR YOUR GIST / ONLINE UPLOAD:")
    print("-" * 50)
    print(json.dumps(users, indent=2, ensure_ascii=False))
    print("=" * 50)
    print("Simply copy this text into your GitHub Gist!\n")


def main():
    while True:
        print("\n" + "═" * 50)
        print("    🔑 LICENSE & USER MANAGER")
        print("═" * 50)
        print("1. ⚡ Generate automatic license key (Recommended)")
        print("2. ✍️ Create custom password/user manually")
        print("3. 📋 View all licenses & users")
        print("4. 🗑️ Delete a license / user")
        print("5. 🌐 Export JSON for online upload (GitHub Gist)")
        print("6. ❌ Exit")
        print("─" * 50)

        choice = input("Choice (1-6): ").strip()

        if choice == "1":
            name = input("Friend's name / Username: ").strip()
            if not name:
                print("❌ Name cannot be empty.")
                continue

            key = create_license_for_friend(name)
            print("\n" + "★" * 50)
            print(f"🎉 New license key for {name} generated:")
            print(f"👉 USERNAME     : {name}")
            print(f"👉 LICENSE KEY  : {key}")
            print("★" * 50)
            print("\nCopy this message and send it to your friend:")
            print(f"\"Here are your login details:\nUsername: {name}\nLicense Key: {key}\"")

        elif choice == "2":
            user = input("Username: ").strip()
            pw = input("Password or custom code: ").strip()
            if user and pw:
                add_manual_user(user, pw)
            else:
                print("❌ Input cannot be empty.")

        elif choice == "3":
            list_users()

        elif choice == "4":
            user = input("Enter the username you want to delete: ").strip()
            users = load_users()
            if user in users:
                del users[user]
                save_users(users)
                print(f"🗑️ '{user}' was successfully removed.")
            else:
                print(f"❌ '{user}' not found.")

        elif choice == "5":
            export_json()

        elif choice == "6":
            print("Exiting.")
            break
        else:
            print("Invalid option, please choose 1 to 6.")


if __name__ == "__main__":
    main()
