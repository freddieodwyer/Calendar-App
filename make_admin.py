import sys

import db

BASE_URL = "https://eleven-lake-probably.ngrok-free.dev"


def main():
    if len(sys.argv) != 2:
        print("Usage: python make_admin.py <group id>   (the part after /g/ in the group link)")
        return
    db.init_db()  # upgrades an older database if needed
    group_id = sys.argv[1]
    if db.get_group(group_id) is None:
        print("No group with that id")
        return
    code = db.set_admin_code(group_id)
    print("Admin link (replaces any older one):")
    print(f"{BASE_URL}/admin/{code}")


main()
