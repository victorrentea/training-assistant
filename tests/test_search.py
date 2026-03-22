
import sys
from quiz_core import search_materials

def test_search(query: str):
    print(f"\n--- Searching for: '{query}' ---")
    results = search_materials(query)
    
    if not results:
        print("No results found.")
        return

    for i, res in enumerate(results, 1):
        print(f"Result {i}:")
        print(f"  Source: {res.get('source', 'N/A')} (Page: {res.get('page', 'N/A')})")
        print(f"  Content snippet: {res.get('content', '')[:200]}...")

if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "Transactional Outbox"
    test_search(query)
