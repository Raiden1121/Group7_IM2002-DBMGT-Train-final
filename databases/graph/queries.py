"""
TransitFlow — Neo4j Graph Database Layer
=========================================
This module handles all queries to Neo4j.

GRAPH ROLE:
  - Model the dual transit network (city metro M1–M4 + national rail NR1–NR2)
  - Find fastest routes (Dijkstra by travel_time_min via APOC)
  - Find cheapest routes (Dijkstra by fare via APOC)
  - Find alternative routes avoiding a given station
  - Find cross-network interchange paths (metro → rail or rail → metro)
  - Show delay ripple: which stations are affected within N hops

STUDENT TASK
------------
Design your graph schema (node labels, relationship types, properties)
based on the data in train-mock-data/, seed it with skeleton/seed_neo4j.py,
then implement the query_ functions below.

Functions prefixed with `query_` are called by the agent (skeleton/agent.py).
"""

from __future__ import annotations

from typing import Optional

from neo4j import GraphDatabase

from skeleton.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD


# Create driver once at module load (singleton) for better connection pooling
# Align with SideNote3-GraphDBPractices.md (1)
_DRIVER = GraphDatabase.driver(
    NEO4J_URI,
    auth=(NEO4J_USER, NEO4J_PASSWORD),
    max_connection_pool_size=50
)


# ── Example ───────────────────────────────────────────────────────────────────
# The block below shows the query pattern: open a session, run Cypher, return data.

def example_count_nodes() -> int:
    """Example: count all nodes currently in the graph."""
    with _DRIVER.session() as session:
        result = session.run("MATCH (n) RETURN count(n) AS total")
        return result.single()["total"]

# TODO: Implement the query_ functions below.
# ─────────────────────────────────────────────────────────────────────────────


# ── FASTEST ROUTE (Dijkstra by travel_time_min) ───────────────────────────────

def query_shortest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
) -> dict:
    """
    Find the fastest path between two stations, minimising total travel time.
    Uses apoc.algo.dijkstra (APOC required; enabled in docker-compose.yml).

    Args:
        origin_id:       e.g. "MS01" or "NR01"
        destination_id:  e.g. "MS09" or "NR05"
        network:         "metro", "rail", or "auto" (inferred from IDs)

    Returns:
        dict with keys: found, origin_id, destination_id,
                        total_time_min, path (list of station dicts), legs
    """
    # Use APOC dijkstra to find shortest path using travel_time_min weight (fastest path).
    # The default weight of 5 mins is a fallback (e.g. if a property is missing),
    # but seed_neo4j.py sets travel_time_min=5 for INTERCHANGE_TO as well.
    query = """
    // Set start and end station ID to variables
    MATCH (start {station_id: $origin_id})
    MATCH (end {station_id: $destination_id})
    CALL apoc.algo.dijkstra(
        start, end, 
        'METRO_LINK|RAIL_LINK|INTERCHANGE_TO', // Consider all possible connections
        'travel_time_min' // Use travel_time_min as weight
    ) YIELD path, weight
    RETURN path, weight AS total_time_min 
    """
    with _DRIVER.session() as session:
        result = session.run(query, origin_id=origin_id, destination_id=destination_id)
        record = result.single()
        
        if not record: # If no path found, return empty result
            return {"found": False, "origin_id": origin_id, "destination_id": destination_id}
            
        path = record["path"] # Get the path
        # Extract nodes and relationships sequentially to form the path and legs lists
        nodes = path.nodes
        rels = path.relationships
        
        stations = [{"station_id": n["station_id"], "name": n["name"]} for n in nodes]
        legs = []
        for r in rels:
            legs.append({
                "type": r.type,
                "time_min": r.get("travel_time_min") or r.get("transfer_time_min") or 5
            })
            
        return {
            "found": True,
            "origin_id": origin_id,
            "destination_id": destination_id,
            "total_time_min": record["total_time_min"],
            "path": stations,
            "legs": legs
        }


# ── CHEAPEST ROUTE (Dijkstra by fare) ────────────────────────────────────────

def query_cheapest_route(
    origin_id: str,
    destination_id: str,
    network: str = "auto",
    fare_class: str = "standard",
) -> dict:
    """
    Find the cheapest path between two stations, minimising total estimated fare.

    Args:
        origin_id:       e.g. "NR01"
        destination_id:  e.g. "NR05"
        network:         "metro", "rail", or "auto"
        fare_class:      "standard" or "first" (national rail only)

    Returns:
        dict with found, total_fare_usd (approximate), stations, legs
    """
    weight_prop = "first_fare_usd" if fare_class == "first" else "standard_fare_usd"
    
    # Following SideNote3 GraphDB Best Practices: We strictly avoid f-strings for Cypher 
    # injection. Instead, we use Cypher parameters (e.g. $weight_prop) to securely and 
    # efficiently pass the dynamic property key to the APOC procedure.
    query = """
    MATCH (start {station_id: $origin_id})
    MATCH (end {station_id: $destination_id})
    CALL apoc.algo.dijkstra(
        start, end, 
        'METRO_LINK|RAIL_LINK|INTERCHANGE_TO', 
        $weight_prop
    ) YIELD path, weight
    RETURN path, weight AS fare_sum
    """
    
    with _DRIVER.session() as session:
        result = session.run(
            query, 
            origin_id=origin_id, 
            destination_id=destination_id,
            weight_prop=weight_prop
        )
        record = result.single()
        
        if not record: # If no path found, return empty result
            return {"found": False, "origin_id": origin_id, "destination_id": destination_id}
            
        path = record["path"] # Get the path
        
        stations = [{"station_id": n["station_id"], "name": n["name"]} for n in path.nodes]
        legs = []
        
        used_metro = False
        used_rail = False
        
        # Iterate all relationships in the path
        for r in path.relationships:
            if r.type == "METRO_LINK":
                used_metro = True
                cost = r.get(weight_prop)
            elif r.type == "RAIL_LINK":
                used_rail = True
                cost = r.get(weight_prop)
            else:
                cost = 0.0
                
            legs.append({
                "type": r.type,
                "fare_cost": cost
            })
            
        # Following the README "Hybrid Approach" rule : 
        total_fare_usd = record["fare_sum"]
        if used_metro:
            total_fare_usd += 0.80  # Metro base boarding fare
            
        if used_rail:
            if fare_class == "first":
                total_fare_usd += 4.00  # NR First base boarding fare
            else:
                total_fare_usd += 2.50  # NR Standard base boarding fare
                
        return {
            "found": True,
            "origin_id": origin_id,
            "destination_id": destination_id,
            "total_fare_usd": round(total_fare_usd, 2),
            "stations": stations,
            "legs": legs
        }


# ── ALTERNATIVE ROUTES (avoiding a station) ───────────────────────────────────

def query_alternative_routes(
    origin_id: str,
    destination_id: str,
    avoid_station_id: str,
    network: str = "auto",
    max_routes: int = 3,
) -> list[list[dict]]:
    """
    Find paths between two stations that avoid a specific intermediate station.
    Useful for routing around a delayed or closed station.

    Args:
        origin_id:         e.g. "NR01"
        destination_id:    e.g. "NR05"
        avoid_station_id:  e.g. "NR03"
        network:           "metro", "rail", or "auto"
        max_routes:        max number of alternatives to return

    Returns:
        List of routes, each route is a list of leg dicts
    """
    # Standard Cypher variable-length path matching.
    # We use `NONE()` predicate to explicitly filter out paths containing the `avoid_station_id`.
    # `coalesce` is used to handle missing `travel_time_min` robustly.
    query = """
    // 1..6 means find the all path with 1 to 6 times interchange (limited to prevent graph explosion)
    MATCH path = (start {station_id: $origin_id})-[:METRO_LINK|RAIL_LINK|INTERCHANGE_TO*1..6]-(end {station_id: $destination_id})
    WHERE NONE(n IN nodes(path) WHERE n.station_id = $avoid_station_id) // Ensuring paths do not contain the avoid station
    WITH path,
         [n IN nodes(path) | {station_id: n.station_id, name: n.name}] AS stations,
         reduce(t=0, r IN relationships(path) | t + coalesce(r.travel_time_min, r.transfer_time_min, 5)) AS total_time_min
    ORDER BY total_time_min ASC
    LIMIT $max_routes // Only take few shortest alternative routes
    RETURN stations, total_time_min
    """
    
    with _DRIVER.session() as session:
        result = session.run(
            query, 
            origin_id=origin_id, 
            destination_id=destination_id, 
            avoid_station_id=avoid_station_id, 
            max_routes=max_routes
        )
        
        routes = []
        for record in result:
            routes.append({
                "stations": record["stations"],
                "total_time_min": record["total_time_min"]
            })
            
        return routes


# ── CROSS-NETWORK INTERCHANGE PATH ───────────────────────────────────────────

def query_interchange_path(origin_id: str, destination_id: str) -> dict:
    """
    Find a path between a metro station and a national rail station (or vice versa)
    crossing the network boundary via interchange relationships.

    Args:
        origin_id:       e.g. "MS03" (metro) or "NR05" (national rail)
        destination_id:  e.g. "NR05" (national rail) or "MS09" (metro)

    Returns:
        dict with found, stations list, interchange points, total_time_min
    """
    # Use APOC dijkstra to find path, then extract INTERCHANGE_TO steps directly
    # from the relationships in the found path.
    query = """  // Same as first TODO
    MATCH (start {station_id: $origin_id})
    MATCH (end {station_id: $destination_id})
    CALL apoc.algo.dijkstra(
        start, end, 
        'METRO_LINK|RAIL_LINK|INTERCHANGE_TO', 
        'travel_time_min'
    ) YIELD path, weight
    RETURN path, weight AS total_time_min
    """
    
    with _DRIVER.session() as session:
        result = session.run(query, origin_id=origin_id, destination_id=destination_id)
        record = result.single()
        
        if not record: # If no path found
            return {"found": False}
            
        path = record["path"] # Get the path
        stations = [{"station_id": n["station_id"], "name": n["name"]} for n in path.nodes]
        
        # NEW : Identify any interchange legs by inspecting relationship types
        interchanges = []
        for r in path.relationships:
            if r.type == "INTERCHANGE_TO":
                interchanges.append({
                    "from_station_id": r.start_node["station_id"],
                    "to_station_id": r.end_node["station_id"]
                })
                
        return {
            "found": True,
            "stations": stations,
            "interchanges": interchanges,
            "total_time_min": record["total_time_min"]
        }


# ── DELAY RIPPLE ANALYSIS ─────────────────────────────────────────────────────

def query_delay_ripple(delayed_station_id: str, hops: int = 2) -> list[dict]:
    """
    Find all stations within N hops of a delayed or disrupted station.
    Works on both metro and national rail networks.

    Args:
        delayed_station_id: e.g. "NR03" or "MS01"
        hops:               how many connections out to search (default 2)

    Returns:
        List of dicts: {station_id, name, hops_away, lines_affected}
    """
    # Cypher shortestPath within a restricted length bounds to naturally
    # figure out the exact 'hops_away' for each affected station.
    # The length bound is hardcoded up to 10 (*1..10) as a safety measure for graph queries.
    query = """
    MATCH (start {station_id: $delayed_station_id})
    MATCH path = shortestPath((start)-[:METRO_LINK|RAIL_LINK|INTERCHANGE_TO*1..10]-(affected))
    WHERE length(path) <= $hops AND start <> affected // Set fliter hops (default 2) and except the delayed station itself
    RETURN affected.station_id AS station_id, 
           affected.name AS name, 
           length(path) AS hops_away, 
           affected.lines AS lines_affected
    ORDER BY hops_away ASC
    """
    
    with _DRIVER.session() as session:
        result = session.run(query, delayed_station_id=delayed_station_id, hops=hops)
        return [dict(r) for r in result]


# ── STATION CONNECTIONS ───────────────────────────────────────────────────────

def query_station_connections(station_id: str) -> list[dict]:
    """
    List all direct connections from a given station.

    Args:
        station_id: e.g. "MS01" or "NR01"
    """
    # A straightforward node expansion query looking at 1-hop outgoing relationships.
    # Easy peasy ~~~~
    query = """
    MATCH (start {station_id: $station_id})-[r]->(connected)
    RETURN connected.station_id AS station_id, 
           connected.name AS name, 
           type(r) AS connection_type, 
           coalesce(r.travel_time_min, r.transfer_time_min, 5) AS time_min
    """
    
    with _DRIVER.session() as session:
        result = session.run(query, station_id=station_id)
        return [dict(r) for r in result]
