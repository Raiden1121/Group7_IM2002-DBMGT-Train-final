"""
TransitFlow — Neo4j Seeder
Run once after starting Docker:
    python skeleton/seed_neo4j.py

Loads station and network data from train-mock-data/:
  - metro_stations.json         — city metro stations and adjacencies
  - national_rail_stations.json — national rail stations and adjacencies

Design your graph schema (node labels, relationship types, properties)
based on the data in these files, then implement the seed() function below.
"""

import json
import os
import sys

sys.path.insert(0, ".")

from neo4j import GraphDatabase
from skeleton.config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

_DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "train-mock-data")
)


def _load(filename):
    with open(os.path.join(_DATA_DIR, filename), encoding="utf-8") as f:
        return json.load(f)


def seed():
    metro_stations = _load("metro_stations.json")
    rail_stations  = _load("national_rail_stations.json")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:

        session.run("MATCH (n) DETACH DELETE n")
        print("  Cleared existing graph data")

        # TODO: Design your node labels and create metro station nodes.
        print("  Creating constraints for best performance...")  #Ensure no same nodes for specific ID
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (m:MetroStation) REQUIRE m.station_id IS UNIQUE") 
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (n:NationalRailStation) REQUIRE n.station_id IS UNIQUE") 

        print("  Seeding MetroStation nodes...")
        for s in metro_stations:
            # Using MERGE ensures we do not create same station when running many times
            session.run(
                """
                MERGE (m:MetroStation {station_id: $id})
                SET m.name = $name, m.lines = $lines
                """,
                id=s["station_id"],  name=s["name"],  lines=s["lines"]
            )

        # TODO: Design your node labels and create national rail station nodes.
        print("  Seeding NationalRailStation nodes...") # Same as logic above
        for s in rail_stations:
            session.run(
                """
                MERGE (n:NationalRailStation {station_id: $id})
                SET n.name = $name, n.lines = $lines
                """,
                id=s["station_id"], name=s["name"], lines=s["lines"]
            )


        # TODO: Design your relationship types and create metro links.
        print("  Seeding METRO_LINK relationships...")
        for s in metro_stations: # through all metro stations
            for adj in s.get("adjacent_stations", []): # through all adjacent stations, if no -> put empty []
                session.run(
                    """
                    MATCH (a:MetroStation {station_id: $id1}) 
                    MATCH (b:MetroStation {station_id: $id2})
                    MERGE (a)-[r:METRO_LINK {line: $line}]->(b)  // Direct from a -> b (One-way Relationship, Two-way will create in other loop)
                    SET r.travel_time_min = $time, r.standard_fare_usd = 0.30, r.first_fare_usd = 0.30  // Set travel time and per-stop fare
                    """,
                    id1=s["station_id"], id2=adj["station_id"], line=adj["line"], time=adj["travel_time_min"]
                )


        # TODO: Design your relationship types and create national rail links.
        print("  Seeding RAIL_LINK relationships...") # Same as logic above
        for s in rail_stations: 
            for adj in s.get("adjacent_stations", []): 
                session.run(
                    """
                    MATCH (a:NationalRailStation {station_id: $id1}) 
                    MATCH (b:NationalRailStation {station_id: $id2})
                    MERGE (a)-[r:RAIL_LINK {line: $line}]->(b)  // Direct from a -> b (Relationship)
                    SET r.travel_time_min = $time, r.standard_fare_usd = 1.50, r.first_fare_usd = 2.50  // Set travel time and per-stop fares
                    """,
                    id1=s["station_id"], id2=adj["station_id"], line=adj["line"], time=adj["travel_time_min"]
                )

        # TODO: Create interchange relationships between metro and rail stations.
        print("  Seeding INTERCHANGE_TO relationships...")
        for s in metro_stations:
            if s.get("is_interchange_national_rail"):
                session.run(
                    """
                    MATCH (m:MetroStation {station_id: $ms_id})
                    MATCH (n:NationalRailStation {station_id: $nr_id})
                    // Create two-way relationships, because we only check metro, but it must be bi-directional for interchange
                    MERGE (m)-[r1:INTERCHANGE_TO]->(n)
                    MERGE (n)-[r2:INTERCHANGE_TO]->(m)
                    SET r1.transfer_time_min = 5, r2.transfer_time_min = 5, r1.travel_time_min = 5, r2.travel_time_min = 5, r1.standard_fare_usd = 0.01, r2.standard_fare_usd = 0.01, r1.first_fare_usd = 0.01, r2.first_fare_usd = 0.01 // Set reasonable walking transfer time for 5 minutes and nearly free fare
                    """,
                    ms_id=s["station_id"],
                    nr_id=s["interchange_national_rail_station_id"]
                )

    driver.close()
    print("\nNeo4j graph seeded successfully.")
    print("   Open http://localhost:7475 to explore the graph.")


if __name__ == "__main__":
    print("Connecting to Neo4j...")
    seed()
