import os
import sys
from sqlalchemy import text, inspect, create_engine, MetaData
from sqlalchemy.orm import sessionmaker

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "src"))

from logos.dbutils.dbmanager import DBManager

def inspect_db():
    print("Initializing DBManager...")
    
    # Patch DBManager to use localhost
    original_enter = DBManager.__enter__
    def patched_enter(self):
        db_url = "postgresql://postgres:root@localhost:5432/logosdb"
        self.engine = create_engine(db_url)
        self.metadata = MetaData()
        self.metadata.reflect(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.session = self.Session()
        return self
        
    DBManager.__enter__ = patched_enter

    try:
        with DBManager() as db:
            print("Connected to DB.")
            
            # Inspect providers table columns
            inspector = inspect(db.engine)
            columns = inspector.get_columns("providers")
            print("\nProviders Table Columns:")
            for col in columns:
                print(f"- {col['name']} ({col['type']})")
                
            # Query providers
            print("\nProviders Content:")
            result = db.session.execute(text("SELECT * FROM providers"))
            for row in result:
                print(row)
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_db()
