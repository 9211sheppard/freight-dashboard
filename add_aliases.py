"""
add_aliases.py — Add proxy email aliases to pricing@flashcargoglobal.com

Strategy: Use Exchange Online REST admin API to set proxy addresses.
The Graph API user.proxyAddresses is read-only for cloud users, but the
Exchange Online Admin API (/adminapi/beta/Mailbox) can modify them.
"""

import json
import urllib.request
import urllib.parse
import urllib.error
import unicodedata
import sys
import time

sys.path.insert(0, r"C:\Users\Owner\Desktop\claude code\contact-dashboard")
from config import GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET

# All country names from mailer.py
_COUNTRY_NAMES = {
    "italy":           ["Marco", "Sofia", "Alessandro", "Giulia", "Luca", "Valentina", "Matteo", "Chiara"],
    "germany":         ["Hans", "Lena", "Markus", "Katrin", "Felix", "Julia", "Thomas", "Sabine"],
    "france":          ["Pierre", "Claire", "Antoine", "Marie", "Julien", "Camille", "Nicolas", "Sophie"],
    "spain":           ["Carlos", "Elena", "Javier", "Lucia", "Pablo", "Isabel", "Miguel", "Carmen"],
    "netherlands":     ["Jan", "Femke", "Daan", "Sanne", "Bram", "Lotte", "Ruben", "Anouk"],
    "belgium":         ["Luc", "Noor", "Thomas", "Charlotte", "Pieter", "Emma", "Wim", "Julie"],
    "switzerland":     ["Stefan", "Anna", "Marc", "Laura", "Daniel", "Sarah", "Lukas", "Elena"],
    "austria":         ["Stefan", "Anna", "Florian", "Lisa", "Markus", "Katharina", "Georg", "Maria"],
    "poland":          ["Piotr", "Kasia", "Tomasz", "Agnieszka", "Jakub", "Magdalena", "Michal", "Anna"],
    "greece":          ["Nikos", "Elena", "Dimitris", "Maria", "Giorgos", "Katerina", "Kostas", "Sofia"],
    "turkey":          ["Mehmet", "Elif", "Ahmet", "Zeynep", "Emre", "Ayse", "Burak", "Fatma"],
    "portugal":        ["João", "Ana", "Tiago", "Beatriz", "Pedro", "Inês", "Miguel", "Carolina"],
    "sweden":          ["Lars", "Elin", "Erik", "Anna", "Oscar", "Maja", "Gustav", "Astrid"],
    "denmark":         ["Mads", "Elin", "Frederik", "Sofie", "Anders", "Ida", "Rasmus", "Katrine"],
    "norway":          ["Lars", "Ingrid", "Magnus", "Sigrid", "Olav", "Astrid", "Henrik", "Solveig"],
    "finland":         ["Mikko", "Aino", "Antti", "Emilia", "Jari", "Sanna", "Ville", "Liisa"],
    "russia":          ["Dmitri", "Natalia", "Alexei", "Olga", "Sergei", "Irina", "Ivan", "Svetlana"],
    "ukraine":         ["Oleksandr", "Natalia", "Andriy", "Oksana", "Dmitro", "Yulia", "Taras", "Iryna"],
    "czech republic":  ["Tomas", "Petra", "Jan", "Lucie", "Pavel", "Tereza", "Martin", "Veronika"],
    "romania":         ["Andrei", "Ioana", "Alexandru", "Maria", "Mihai", "Elena", "Stefan", "Ana"],
    "hungary":         ["Zoltan", "Reka", "Balazs", "Anna", "Gabor", "Eszter", "Laszlo", "Katalin"],
    "croatia":         ["Ivan", "Ana", "Marko", "Petra", "Luka", "Marina", "Ante", "Ivana"],
    "ireland":         ["Sean", "Sinead", "Conor", "Ciara", "Padraig", "Aoife", "Brendan", "Niamh"],
    "united kingdom":  ["James", "Sarah", "William", "Emma", "Oliver", "Charlotte", "George", "Sophie"],
    "uk":              ["James", "Sarah", "William", "Emma", "Oliver", "Charlotte", "George", "Sophie"],
    "china":           ["Wei", "Mei", "Chen", "Li", "Hao", "Xiao", "Jun", "Yan"],
    "hong kong":       ["Wei", "Mei", "Jason", "Winnie", "Kevin", "Rachel", "Alan", "Jenny"],
    "taiwan":          ["Wei", "Mei", "Ming", "Ting", "Yi", "Wen", "Cheng", "Hui"],
    "japan":           ["Kenji", "Yuki", "Takeshi", "Sakura", "Hiroshi", "Aiko", "Ryo", "Hana"],
    "south korea":     ["Min", "Soo", "Hyun", "Ji", "Joon", "Eun", "Sung", "Yeon"],
    "korea":           ["Min", "Soo", "Hyun", "Ji", "Joon", "Eun", "Sung", "Yeon"],
    "india":           ["Raj", "Priya", "Arjun", "Anita", "Vikram", "Deepa", "Amit", "Sunita"],
    "singapore":       ["Jun", "Li", "Jason", "Rachel", "Kevin", "Michelle", "Aaron", "Grace"],
    "malaysia":        ["Ahmad", "Siti", "Farid", "Nurul", "Hafiz", "Ain", "Azlan", "Fatimah"],
    "indonesia":       ["Budi", "Sari", "Andi", "Dewi", "Rizal", "Putri", "Agus", "Sri"],
    "thailand":        ["Chai", "Noi", "Somchai", "Ploy", "Natthapong", "Kannika", "Prawit", "Siriporn"],
    "vietnam":         ["Minh", "Lan", "Duc", "Linh", "Tuan", "Mai", "Hung", "Thao"],
    "philippines":     ["Rico", "Maria", "Juan", "Rosa", "Miguel", "Ana", "Rafael", "Luz"],
    "australia":       ["James", "Sarah", "Ryan", "Emma", "Liam", "Chloe", "Jack", "Mia"],
    "new zealand":     ["James", "Sarah", "Ben", "Kate", "Sam", "Lucy", "Matt", "Hannah"],
    "bangladesh":      ["Rahim", "Nadia", "Farhan", "Amina", "Hasan", "Fatema", "Kamal", "Yasmin"],
    "pakistan":         ["Ali", "Fatima", "Hassan", "Ayesha", "Bilal", "Sana", "Usman", "Zainab"],
    "sri lanka":       ["Ashan", "Dilini", "Nuwan", "Sachini", "Chaminda", "Nishanthi", "Ruwan", "Apsara"],
    "usa":             ["Mike", "Jessica", "Brian", "Amanda", "Ryan", "Stephanie", "Chris", "Nicole"],
    "united states":   ["Mike", "Jessica", "Brian", "Amanda", "Ryan", "Stephanie", "Chris", "Nicole"],
    "brazil":          ["Bruno", "Ana", "Rafael", "Juliana", "Lucas", "Fernanda", "Gustavo", "Camila"],
    "mexico":          ["Diego", "Paola", "Alejandro", "Daniela", "Fernando", "Valeria", "Luis", "Mariana"],
    "colombia":        ["Andres", "Paola", "Sebastian", "Daniela", "Juan", "Natalia", "Carlos", "Laura"],
    "argentina":       ["Martin", "Florencia", "Santiago", "Valentina", "Nicolas", "Camila", "Matias", "Sol"],
    "chile":           ["Rodrigo", "Constanza", "Felipe", "Francisca", "Ignacio", "Catalina", "Diego", "Javiera"],
    "peru":            ["Ricardo", "Paola", "Jose", "Milagros", "Carlos", "Valeria", "Luis", "Maria"],
    "canada":          ["James", "Sarah", "Ryan", "Emma", "Michael", "Chloe", "David", "Emily"],
    "ecuador":         ["Luis", "Maria", "Andres", "Gabriela", "Diego", "Valeria", "Carlos", "Daniela"],
    "venezuela":       ["Carlos", "Maria", "Andres", "Gabriela", "Diego", "Valentina", "Luis", "Daniela"],
    "costa rica":      ["Jose", "Maria", "Luis", "Daniela", "Carlos", "Valeria", "Diego", "Andrea"],
    "panama":          ["Roberto", "Maria", "Luis", "Daniela", "Carlos", "Ana", "Jose", "Isabel"],
    "uae":             ["Khalid", "Fatima", "Ahmed", "Mariam", "Omar", "Sara", "Rashid", "Noor"],
    "united arab emirates": ["Khalid", "Fatima", "Ahmed", "Mariam", "Omar", "Sara", "Rashid", "Noor"],
    "saudi arabia":    ["Khalid", "Fatima", "Mohammed", "Noura", "Abdullah", "Hala", "Fahad", "Reem"],
    "qatar":           ["Khalid", "Fatima", "Hamad", "Mariam", "Ali", "Noura", "Saad", "Maha"],
    "kuwait":          ["Khalid", "Fatima", "Fahad", "Noura", "Bader", "Dana", "Salem", "Dalal"],
    "bahrain":         ["Khalid", "Fatima", "Ahmed", "Noura", "Ali", "Mariam", "Hassan", "Sara"],
    "oman":            ["Khalid", "Fatima", "Said", "Mariam", "Ahmed", "Khadija", "Hamad", "Noura"],
    "egypt":           ["Ahmed", "Fatima", "Mohamed", "Noura", "Khaled", "Mona", "Hassan", "Yasmin"],
    "jordan":          ["Khaled", "Fatima", "Ahmad", "Rania", "Omar", "Lina", "Faisal", "Dina"],
    "lebanon":         ["Rami", "Nadia", "Fadi", "Rita", "Sami", "Maya", "Tony", "Carla"],
    "israel":          ["David", "Noa", "Eyal", "Tamar", "Avi", "Yael", "Oren", "Shira"],
    "south africa":    ["James", "Sarah", "Thabo", "Naledi", "Pieter", "Lerato", "Johan", "Nandi"],
    "nigeria":         ["Emeka", "Amara", "Chukwu", "Ngozi", "Ade", "Funke", "Tunde", "Chioma"],
    "kenya":           ["James", "Amina", "John", "Wanjiku", "Peter", "Akinyi", "David", "Njeri"],
    "ghana":           ["Kofi", "Ama", "Kwame", "Akosua", "Yaw", "Abena", "Kwesi", "Adwoa"],
    "tanzania":        ["James", "Amina", "Joseph", "Rehema", "John", "Neema", "Charles", "Zainab"],
    "morocco":         ["Youssef", "Salma", "Amine", "Fatima", "Mehdi", "Khadija", "Omar", "Layla"],
}

RESERVED_NAMES = {"admin", "robyn", "jeffrey", "pricing"}


def strip_accents(s):
    nfkd = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in nfkd if not unicodedata.combining(c))


def get_unique_names():
    names = set()
    for country_names in _COUNTRY_NAMES.values():
        for name in country_names:
            clean = strip_accents(name).lower().strip()
            if clean and clean not in RESERVED_NAMES:
                names.add(clean)
    return sorted(names)


def get_graph_token():
    url = f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}/oauth2/v2.0/token"
    body = urllib.parse.urlencode({
        "grant_type":    "client_credentials",
        "client_id":     GRAPH_CLIENT_ID,
        "client_secret": GRAPH_CLIENT_SECRET,
        "scope":         "https://graph.microsoft.com/.default",
    }).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["access_token"]


def check_app_permissions(token):
    """Check what permissions the app has."""
    # Check service principal permissions
    url = f"https://graph.microsoft.com/v1.0/servicePrincipals?$filter=appId eq '{GRAPH_CLIENT_ID}'&$select=id,appRoles,oauth2PermissionScopes"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            print(f"  Service principal found: {len(data.get('value', []))} entries")
            if data.get('value'):
                sp = data['value'][0]
                print(f"  SP ID: {sp.get('id')}")
    except urllib.error.HTTPError as e:
        print(f"  Could not check permissions: {e.code}")


def get_user_id(token):
    """Get the user ID for pricing@ to use in other APIs."""
    url = "https://graph.microsoft.com/v1.0/users/pricing@flashcargoglobal.com?$select=id,userPrincipalName,proxyAddresses,mail"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def try_directory_objects_patch(token, user_id, all_addresses):
    """
    Try patching via /directoryObjects endpoint which sometimes has
    different permission requirements.
    """
    url = f"https://graph.microsoft.com/v1.0/directoryObjects/{user_id}"
    payload = json.dumps({
        "@odata.type": "#microsoft.graph.user",
        "proxyAddresses": all_addresses
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="PATCH")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"  directoryObjects PATCH success: {resp.status}")
            return True
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        print(f"  directoryObjects PATCH failed ({e.code}): {err[:200]}")
        return False


def try_user_patch_with_directory_role(token, all_addresses):
    """
    Try PATCH /users with proper permission. The User.ReadWrite.All
    permission should work for modifying proxyAddresses on cloud users.
    But M365 has a quirk: proxyAddresses on CLOUD users can only be
    modified by Directory.ReadWrite.All, not User.ReadWrite.All.
    """
    url = "https://graph.microsoft.com/v1.0/users/pricing@flashcargoglobal.com"
    payload = json.dumps({"proxyAddresses": all_addresses}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="PATCH")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"  User PATCH success: {resp.status}")
            return True
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        err_data = json.loads(err)
        code = err_data.get("error", {}).get("code", "")
        msg = err_data.get("error", {}).get("message", "")
        print(f"  User PATCH failed ({e.code}): {code} - {msg}")
        return False


def try_mailbox_settings(token, all_addresses):
    """
    Alternative: try using /users/{id}/mailboxSettings or the
    Exchange configuration endpoint.
    """
    # Try the outlook-specific endpoint
    url = "https://graph.microsoft.com/v1.0/users/pricing@flashcargoglobal.com/mailboxSettings"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            print(f"  Mailbox settings: {json.dumps(data, indent=2)[:300]}")
    except urllib.error.HTTPError as e:
        print(f"  Mailbox settings read failed: {e.code}")
    return False


def main():
    names = get_unique_names()
    print(f"Found {len(names)} unique first names")
    print()

    print("Getting Graph API token...")
    token = get_graph_token()
    print("  Done")

    print()
    print("Checking app permissions...")
    check_app_permissions(token)

    print()
    print("Getting user info...")
    user_data = get_user_id(token)
    user_id = user_data["id"]
    current_proxies = user_data.get("proxyAddresses", [])
    print(f"  User ID: {user_id}")
    print(f"  UPN: {user_data.get('userPrincipalName')}")
    print(f"  Mail: {user_data.get('mail')}")
    print(f"  Current proxyAddresses: {current_proxies}")

    # Build full address list
    existing_lower = {a.lower() for a in current_proxies}
    all_addresses = list(current_proxies)
    new_names = []
    for name in names:
        alias = f"smtp:{name}@flashcargoglobal.com"
        if alias.lower() not in existing_lower:
            all_addresses.append(alias)
            new_names.append(name)
            existing_lower.add(alias.lower())

    print(f"\n  New aliases to add: {len(new_names)}")
    print(f"  Total addresses after: {len(all_addresses)}")

    # Try approach 1: standard PATCH /users
    print("\n--- Approach 1: PATCH /users ---")
    if try_user_patch_with_directory_role(token, all_addresses):
        print("SUCCESS!")
        return verify_and_report(token)

    # Try approach 2: PATCH /directoryObjects
    print("\n--- Approach 2: PATCH /directoryObjects ---")
    if try_directory_objects_patch(token, user_id, all_addresses):
        print("SUCCESS!")
        return verify_and_report(token)

    # Try approach 3: beta endpoint
    print("\n--- Approach 3: PATCH /beta/users ---")
    url = f"https://graph.microsoft.com/beta/users/pricing@flashcargoglobal.com"
    payload = json.dumps({"proxyAddresses": all_addresses}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="PATCH")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"  Beta PATCH success: {resp.status}")
            print("SUCCESS!")
            return verify_and_report(token)
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        print(f"  Beta PATCH failed ({e.code}): {err[:200]}")

    # All Graph approaches failed — need Exchange.ManageAsApp or admin-level permissions
    print("\n" + "=" * 70)
    print("Graph API approaches exhausted.")
    print()
    print("For cloud-only M365 users, modifying proxyAddresses requires one of:")
    print("  1. Exchange.ManageAsApp + Exchange Administrator role assignment")
    print("  2. Directory.ReadWrite.All application permission (instead of User.ReadWrite.All)")
    print("  3. Manual addition via M365 Admin Center")
    print()
    print("The app currently has User.ReadWrite.All, but proxyAddresses for")
    print("cloud users is managed by Exchange and needs either:")
    print("  - Directory.ReadWrite.All permission on the app, OR")
    print("  - Exchange.ManageAsApp with the app assigned Exchange Admin role")
    print()

    # Check what we actually need
    print("RECOMMENDATION: Add Directory.ReadWrite.All to the app registration.")
    print("  1. Go to Azure Portal > App registrations > Freight Dashboard Mailer")
    print("  2. API permissions > Add permission > Microsoft Graph > Application")
    print("  3. Add 'Directory.ReadWrite.All'")
    print("  4. Grant admin consent")
    print("  5. Re-run this script")
    print()
    print("OR: Try the alternative approach using Exchange.ManageAsApp:")
    print("  1. Azure Portal > App registrations > API permissions")
    print("  2. Add 'Office 365 Exchange Online' > Application > Exchange.ManageAsApp")
    print("  3. Azure Portal > Roles and administrators > Exchange Administrator")
    print("  4. Add the app's service principal to this role")
    print("  5. Re-run this script")

    return False


def verify_and_report(token):
    """Verify the aliases were added and print summary."""
    print("\nVerifying...")
    time.sleep(2)
    user = get_user_id(token)
    proxies = user.get("proxyAddresses", [])
    print(f"  Total proxy addresses: {len(proxies)}")
    for p in sorted(proxies)[:20]:
        print(f"    {p}")
    if len(proxies) > 20:
        print(f"    ... and {len(proxies) - 20} more")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
