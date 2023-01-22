from sqlalchemy_utils import create_database, database_exists
import sys
from db.database import DATABASE_URL

if __name__ == "__main__":
    print("Creating DB...", file=sys.stderr)
    if not database_exists(DATABASE_URL):
        create_database(DATABASE_URL)
    print("DB successfully created", file=sys.stderr)
