"""Cypher query registry for Company Brain.

Per ARCHITECTURE.md sections 2, 9, 16:
- Cypher lives ONLY in this file (outside of ingest loaders).
- Named uppercase constants Q01..Q27 (Q10 is unused).
- Multi-statement entries are split into uppercase suffixed constants (Q11A..Q11D, Q15A..Q15C, Q22A..Q22B).
- QUERY_DOCS dictionary maps each constant to its one-line description for doc generation.
"""

# Q01: Formal owners of a module
Q01 = """MATCH (t:Team)-[:OWNS]->(m:Module {id:$module_id})
OPTIONAL MATCH (p:Person)-[:MEMBER_OF]->(t)
RETURN t.id AS team_id, t.display AS team, collect(p.id) AS member_ids"""

# Q02: De facto contributors of a module
Q02 = """MATCH (p:Person)-[:AUTHORED]->(pr:PR)-[:TOUCHES]->(:File)-[:PART_OF]->(m:Module {id:$module_id})
RETURN p.id AS person_id, p.display AS person, count(DISTINCT pr) AS pr_count, max(pr.merged_at) AS last_active
ORDER BY pr_count DESC LIMIT $limit"""

# Q03: Resolve module by name or path
Q03 = """MATCH (m:Module)
WHERE toLower(m.display) CONTAINS toLower($q) OR toLower(m.path) CONTAINS toLower($q)
RETURN m.id AS id, m.display AS display, m.path AS path LIMIT 5"""

# Q04: Vector search, executed once per label in $label (Decision | Doc | Thread)
Q04 = """CALL db.idx.vector.queryNodes($label, 'embedding', $k, vecf32($vec)) YIELD node, score
RETURN node.id AS id, labels(node)[0] AS label, node.display AS display, node.url AS url, score"""

# Q05: Decision with all neighbors
Q05 = """MATCH (d:Decision {id:$id})
OPTIONAL MATCH (d)-[:DECIDED_BY]->(p:Person)
OPTIONAL MATCH (d)-[:AFFECTS]->(m:Module)
OPTIONAL MATCH (d)-[:DOCUMENTED_IN]->(doc:Doc)
OPTIONAL MATCH (d)-[:DISCUSSED_IN]->(th:Thread)
OPTIONAL MATCH (d)-[:TRACKED_BY]->(tk:Ticket)
OPTIONAL MATCH (pr:PR)-[:IMPLEMENTS]->(d)
RETURN d, p, collect(DISTINCT m) AS modules, collect(DISTINCT doc) AS docs,
       collect(DISTINCT th) AS threads, collect(DISTINCT tk) AS tickets, collect(DISTINCT pr) AS prs"""

# Q06: Decisions that supersede this one (forward chain)
Q06 = """MATCH path = (d:Decision {id:$id})-[:SUPERSEDED_BY*1..5]->(n:Decision) RETURN path"""

# Q07: Decisions this one supersedes (backward chain)
Q07 = """MATCH path = (o:Decision)-[:SUPERSEDED_BY*1..5]->(d:Decision {id:$id}) RETURN path"""

# Q08: Later PRs that touched what the decision affects (drift detail for one decision)
Q08 = """MATCH (d:Decision {id:$id})-[:AFFECTS]->(m:Module)
MATCH (pr:PR)-[:TOUCHES]->(:File)-[:PART_OF]->(m)
WHERE pr.merged_at IS NOT NULL AND pr.merged_at > d.decided_at AND NOT (pr)-[:IMPLEMENTS]->(d)
RETURN DISTINCT pr.id AS pr_id, pr.display AS title, pr.merged_at AS merged_at, m.id AS module_id
ORDER BY merged_at DESC LIMIT $limit"""

# Q09: Drift counts for ALL decisions (freshness classification happens in freshness.py)
Q09 = """MATCH (d:Decision)
OPTIONAL MATCH (d)-[:AFFECTS]->(m:Module)<-[:PART_OF]-(:File)<-[:TOUCHES]-(pr:PR)
WHERE pr.merged_at > d.decided_at AND NOT (pr)-[:IMPLEMENTS]->(d)
WITH d, count(DISTINCT pr) AS drift_count, max(pr.merged_at) AS latest
OPTIONAL MATCH (d)-[:DECIDED_BY]->(p:Person)
OPTIONAL MATCH (d)-[:AFFECTS]->(m2:Module)
RETURN d.id AS id, d.display AS title, d.decided_at AS decided_at, d.status AS status,
       drift_count, latest, p.display AS decider, collect(DISTINCT m2.id) AS module_ids
ORDER BY drift_count DESC"""

# Q11A: who_knows score component from authored PRs over $module_ids
Q11A = """MATCH (p:Person)-[:AUTHORED]->(pr:PR)-[:TOUCHES]->(:File)-[:PART_OF]->(m:Module)
WHERE m.id IN $module_ids
RETURN p.id AS person_id, count(DISTINCT pr) AS prs"""

# Q11B: who_knows score component from participated threads over $module_ids
Q11B = """MATCH (p:Person)-[:PARTICIPATED_IN]->(th:Thread)-[:MENTIONS]->(m:Module)
WHERE m.id IN $module_ids
RETURN p.id AS person_id, count(DISTINCT th) AS threads"""

# Q11C: who_knows score component from decided decisions over $module_ids
Q11C = """MATCH (d:Decision)-[:AFFECTS]->(m:Module), (d)-[:DECIDED_BY]->(p:Person)
WHERE m.id IN $module_ids
RETURN p.id AS person_id, count(DISTINCT d) AS decisions"""

# Q11D: Person details
Q11D = """MATCH (p:Person) WHERE p.id IN $ids RETURN p.id AS id, p.display AS display, p.role AS role"""

# Q12: Recent changes in a module
Q12 = """MATCH (pr:PR)-[:TOUCHES]->(:File)-[:PART_OF]->(m:Module {id:$module_id})
WHERE pr.merged_at >= $since
RETURN DISTINCT pr.id AS id, pr.display AS title, pr.merged_at AS merged_at
ORDER BY merged_at DESC LIMIT $limit"""

# Q13: Shortest connection between two nodes, any labels
Q13 = """MATCH (a {id:$a}), (b {id:$b})
WITH shortestPath((a)-[*..6]-(b)) AS p
RETURN p"""

# Q14: PageRank over the collaboration graph
Q14 = """CALL algo.pageRank('Person', 'COLLABORATES_WITH') YIELD node, score
RETURN node.id AS id, node.display AS display, score
ORDER BY score DESC LIMIT $limit"""

# Q15A: Existing open review for a decision
Q15A = """MATCH (r:ReviewRequest {status:'open'})-[:REVIEWS]->(:Decision {id:$decision_id}) RETURN r.id AS id LIMIT 1"""

# Q15B: Create review request
Q15B = """MATCH (d:Decision {id:$decision_id})
CREATE (r:ReviewRequest {id:$rr_id, display:$display, note:$note, status:'open', created_at:$now, source:'agent'})
CREATE (r)-[:REVIEWS]->(d)
RETURN r.id AS id"""

# Q15C: Assign review to the decider
Q15C = """MATCH (r:ReviewRequest {id:$rr_id}), (:Decision {id:$decision_id})-[:DECIDED_BY]->(p:Person)
CREATE (r)-[:ASSIGNED_TO]->(p)
RETURN p.id AS person_id, p.display AS person"""

# Q16: Derive collaboration edges (ingest-time)
Q16 = """MATCH (a:Person)-[:AUTHORED]->(:PR)-[:TOUCHES]->(:File)-[:PART_OF]->(m:Module)<-[:PART_OF]-(:File)<-[:TOUCHES]-(:PR)<-[:AUTHORED]-(b:Person)
WHERE a.id <> b.id
WITH a, b, count(DISTINCT m) AS shared
MERGE (a)-[c:COLLABORATES_WITH]->(b)
SET c.weight = shared"""

# Q17: Overview graph (decisions and their neighbors)
Q17 = """MATCH (d:Decision)-[r]-(n) RETURN d, r, n LIMIT $limit"""

# Q18: One-hop neighborhood
Q18 = """MATCH (a {id:$id})-[r]-(n) RETURN a, r, n LIMIT $limit"""

# Q19: Node detail
Q19 = """MATCH (n {id:$id})
OPTIONAL MATCH (n)-[r]-()
RETURN n, labels(n)[0] AS label, count(r) AS degree"""

# Q20: Review requests
Q20 = """MATCH (r:ReviewRequest)-[:REVIEWS]->(d:Decision)
OPTIONAL MATCH (r)-[:ASSIGNED_TO]->(p:Person)
RETURN r, d.id AS decision_id, d.display AS decision, collect(p.id) AS assignee_ids
ORDER BY r.created_at DESC"""

# Q21: Demo: simulate a merged PR touching a module
Q21 = """MATCH (m:Module {id:$module_id})
MERGE (f:File {id:$file_id})
  SET f.path = $path, f.display = $path, f.source = 'synthetic', f.synthetic_demo = true
MERGE (f)-[:PART_OF]->(m)
CREATE (pr:PR {id:$pr_id, number:$number, display:$title, state:'merged', merged_at:$now,
               created_at:$now, source:'synthetic', synthetic_demo:true})
CREATE (pr)-[:TOUCHES]->(f)
RETURN pr.id AS id"""

# Q22A: Demo reset: delete synthetic demo nodes
Q22A = """MATCH (n) WHERE n.synthetic_demo = true DETACH DELETE n"""

# Q22B: Demo reset: delete review requests
Q22B = """MATCH (r:ReviewRequest) DETACH DELETE r"""

# Q23: Modules referenced by search hits
Q23 = """MATCH (n)-[:MENTIONS|AFFECTS]->(m:Module) WHERE n.id IN $ids
RETURN DISTINCT m.id AS id, m.display AS display"""

# Q24: Next demo PR number
Q24 = """MATCH (pr:PR {synthetic_demo:true}) RETURN coalesce(max(pr.number), 899999) AS n"""

# Q25: Modules with owning team
Q25 = """MATCH (m:Module)
OPTIONAL MATCH (t:Team)-[:OWNS]->(m)
RETURN m.id AS id, m.display AS display, m.path AS path, t.display AS owner_team
ORDER BY m.path"""

# Q26: Node counts per label
Q26 = """MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n"""

# Q27: Relationship counts per type
Q27 = """MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n"""

# Documentation dictionary mapping each constant name to a one-line description
QUERY_DOCS = {
    "Q01": "Formal owners of a module and team members",
    "Q02": "De facto contributors of a module based on authored PRs",
    "Q03": "Resolve module by display name or directory path substring",
    "Q04": "Vector search across embeddings for Decision, Doc, or Thread nodes",
    "Q05": "Decision node with all connected neighbors (modules, docs, threads, tickets, PRs)",
    "Q06": "Forward supersession chain for a decision",
    "Q07": "Backward supersession chain for a decision",
    "Q08": "Later PRs touching affected modules (drift detail for a single decision)",
    "Q09": "Drift counts and latest drift timestamps for all decisions",
    "Q11A": "Author PR count component for who_knows expertise scoring",
    "Q11B": "Thread participation count component for who_knows expertise scoring",
    "Q11C": "Authored decision count component for who_knows expertise scoring",
    "Q11D": "Person profile details (display name, role)",
    "Q12": "Recent PR changes touching a specific module",
    "Q13": "Shortest connection path between any two graph nodes",
    "Q14": "PageRank centrality calculation over person-to-person collaboration edges",
    "Q15A": "Find existing open review request for a decision",
    "Q15B": "Create new review request for a decision",
    "Q15C": "Assign review request to the original decision author",
    "Q16": "Derive collaboration edges between authors sharing touched modules",
    "Q17": "Overview subgraph containing decisions and their immediate neighbors",
    "Q18": "One-hop neighborhood subgraph around an arbitrary node",
    "Q19": "Individual node detail with label and degree count",
    "Q20": "All review requests ordered by creation time with decision details",
    "Q21": "Simulate a merged demo PR touching a module",
    "Q22A": "Demo reset: delete all synthetic demo PR and File nodes",
    "Q22B": "Demo reset: delete all ReviewRequest nodes",
    "Q23": "Resolve codebase modules mentioned or affected by search hits",
    "Q24": "Find current maximum demo PR number for sequence generation",
    "Q25": "List all modules sorted by path with formal owning team",
    "Q26": "Count of graph nodes grouped by label",
    "Q27": "Count of graph relationships grouped by relationship type",
}
