import json
from databases.graph.queries import (
    query_shortest_route,
    query_alternative_routes,
    query_interchange_path,
    query_delay_ripple,
    query_station_connections,
    query_cheapest_route
)

print("--- Testing shortest route (MS01 -> MS14) ---")
res = query_shortest_route("MS01", "MS14")
print(json.dumps(res, indent=2))

print("\n--- Testing interchange path (MS01 -> NR05) ---")
res = query_interchange_path("MS01", "NR05")
print(json.dumps(res, indent=2))

print("\n--- Testing alternative routes (NR01 -> NR05 avoid NR03) ---")
res = query_alternative_routes("NR01", "NR05", avoid_station_id="NR03")
print(json.dumps(res, indent=2))

print("\n--- Testing delay ripple (NR01, 1 hop) ---")
res = query_delay_ripple("NR01", hops=1)
print(json.dumps(res, indent=2))

print("\n--- Testing station connections (MS01) ---")
res = query_station_connections("MS01")
print(json.dumps(res, indent=2))

print("\n--- Testing cheapest route (NR01 -> NR05, Standard Fare) ---")
res = query_cheapest_route("NR01", "NR05", fare_class="standard")
print(json.dumps(res, indent=2))

print("\n--- Testing cheapest route (NR01 -> NR05, First Class Fare) ---")
res = query_cheapest_route("NR01", "NR05", fare_class="first")
print(json.dumps(res, indent=2))

print("\n--- Testing cheapest route (MS01 -> NR05, cross-network) ---")
res = query_cheapest_route("MS01", "NR05", fare_class="standard")
print(json.dumps(res, indent=2))
