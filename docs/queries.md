# Cypher Queries and Graph Algorithms Registry

> *Note: This file is GENERATED automatically by `scripts/gen_queries_doc.py`. Do not hand-edit.*

## Summary Table

| ID | Description |
|---|---|
| [`Q01`](#q01) | Formal owners of a module and team members |
| [`Q02`](#q02) | De facto contributors of a module based on authored PRs |
| [`Q03`](#q03) | Resolve module by display name or directory path substring |
| [`Q04`](#q04) | Vector search across embeddings for Decision, Doc, or Thread nodes |
| [`Q05`](#q05) | Decision node with all connected neighbors (modules, docs, threads, tickets, PRs) |
| [`Q06`](#q06) | Forward supersession chain for a decision |
| [`Q07`](#q07) | Backward supersession chain for a decision |
| [`Q08`](#q08) | Later PRs touching affected modules (drift detail for a single decision) |
| [`Q09`](#q09) | Drift counts and latest drift timestamps for all decisions |
| [`Q11A`](#q11a) | Author PR count component for who_knows expertise scoring |
| [`Q11B`](#q11b) | Thread participation count component for who_knows expertise scoring |
| [`Q11C`](#q11c) | Authored decision count component for who_knows expertise scoring |
| [`Q11D`](#q11d) | Person profile details (display name, role) |
| [`Q12`](#q12) | Recent PR changes touching a specific module |
| [`Q13`](#q13) | Shortest connection path between any two graph nodes |
| [`Q14`](#q14) | PageRank centrality calculation over person-to-person collaboration edges |
| [`Q15A`](#q15a) | Find existing open review request for a decision |
| [`Q15B`](#q15b) | Create new review request for a decision |
| [`Q15C`](#q15c) | Assign review request to the original decision author |
| [`Q16`](#q16) | Derive collaboration edges between authors sharing touched modules |
| [`Q17`](#q17) | Overview subgraph containing decisions and their immediate neighbors |
| [`Q18`](#q18) | One-hop neighborhood subgraph around an arbitrary node |
| [`Q19`](#q19) | Individual node detail with label and degree count |
| [`Q20`](#q20) | All review requests ordered by creation time with decision details |
| [`Q21`](#q21) | Simulate a merged demo PR touching a module |
| [`Q22A`](#q22a) | Demo reset: delete all synthetic demo PR and File nodes |
| [`Q22B`](#q22b) | Demo reset: delete all ReviewRequest nodes |
| [`Q23`](#q23) | Resolve codebase modules mentioned or affected by search hits |
| [`Q24`](#q24) | Find current maximum demo PR number for sequence generation |
| [`Q25`](#q25) | List all modules sorted by path with formal owning team |
| [`Q26`](#q26) | Count of graph nodes grouped by label |
| [`Q27`](#q27) | Count of graph relationships grouped by relationship type |

## Query Definitions

### Q01

**Description:** Formal owners of a module and team members

```cypher
MATCH (t:Team)-[:OWNS]->(m:Module {id:$module_id})
OPTIONAL MATCH (p:Person)-[:MEMBER_OF]->(t)
RETURN t.id AS team_id, t.display AS team, collect(p.id) AS member_ids
```

### Q02

**Description:** De facto contributors of a module based on authored PRs

```cypher
MATCH (p:Person)-[:AUTHORED]->(pr:PR)-[:TOUCHES]->(:File)-[:PART_OF]->(m:Module {id:$module_id})
RETURN p.id AS person_id, p.display AS person, count(DISTINCT pr) AS pr_count, max(pr.merged_at) AS last_active
ORDER BY pr_count DESC LIMIT $limit
```

### Q03

**Description:** Resolve module by display name or directory path substring

```cypher
MATCH (m:Module)
WHERE toLower(m.display) CONTAINS toLower($q) OR toLower(m.path) CONTAINS toLower($q)
RETURN m.id AS id, m.display AS display, m.path AS path LIMIT 5
```

### Q04

**Description:** Vector search across embeddings for Decision, Doc, or Thread nodes

```cypher
CALL db.idx.vector.queryNodes($label, 'embedding', $k, vecf32($vec)) YIELD node, score
RETURN node.id AS id, labels(node)[0] AS label, node.display AS display, node.url AS url, score
```

### Q05

**Description:** Decision node with all connected neighbors (modules, docs, threads, tickets, PRs)

```cypher
MATCH (d:Decision {id:$id})
OPTIONAL MATCH (d)-[:DECIDED_BY]->(p:Person)
OPTIONAL MATCH (d)-[:AFFECTS]->(m:Module)
OPTIONAL MATCH (d)-[:DOCUMENTED_IN]->(doc:Doc)
OPTIONAL MATCH (d)-[:DISCUSSED_IN]->(th:Thread)
OPTIONAL MATCH (d)-[:TRACKED_BY]->(tk:Ticket)
OPTIONAL MATCH (pr:PR)-[:IMPLEMENTS]->(d)
RETURN d, p, collect(DISTINCT m) AS modules, collect(DISTINCT doc) AS docs,
       collect(DISTINCT th) AS threads, collect(DISTINCT tk) AS tickets, collect(DISTINCT pr) AS prs
```

### Q06

**Description:** Forward supersession chain for a decision

```cypher
MATCH path = (d:Decision {id:$id})-[:SUPERSEDED_BY*1..5]->(n:Decision) RETURN path
```

### Q07

**Description:** Backward supersession chain for a decision

```cypher
MATCH path = (o:Decision)-[:SUPERSEDED_BY*1..5]->(d:Decision {id:$id}) RETURN path
```

### Q08

**Description:** Later PRs touching affected modules (drift detail for a single decision)

```cypher
MATCH (d:Decision {id:$id})-[:AFFECTS]->(m:Module)
MATCH (pr:PR)-[:TOUCHES]->(:File)-[:PART_OF]->(m)
WHERE pr.merged_at IS NOT NULL AND pr.merged_at > d.decided_at AND NOT (pr)-[:IMPLEMENTS]->(d)
RETURN DISTINCT pr.id AS pr_id, pr.display AS title, pr.merged_at AS merged_at, m.id AS module_id
ORDER BY merged_at DESC LIMIT $limit
```

### Q09

**Description:** Drift counts and latest drift timestamps for all decisions

```cypher
MATCH (d:Decision)
OPTIONAL MATCH (d)-[:AFFECTS]->(m:Module)<-[:PART_OF]-(:File)<-[:TOUCHES]-(pr:PR)
WHERE pr.merged_at > d.decided_at AND NOT (pr)-[:IMPLEMENTS]->(d)
WITH d, count(DISTINCT pr) AS drift_count, max(pr.merged_at) AS latest
OPTIONAL MATCH (d)-[:DECIDED_BY]->(p:Person)
OPTIONAL MATCH (d)-[:AFFECTS]->(m2:Module)
RETURN d.id AS id, d.display AS title, d.decided_at AS decided_at, d.status AS status,
       drift_count, latest, p.display AS decider, collect(DISTINCT m2.id) AS module_ids
ORDER BY drift_count DESC
```

### Q11A

**Description:** Author PR count component for who_knows expertise scoring

```cypher
MATCH (p:Person)-[:AUTHORED]->(pr:PR)-[:TOUCHES]->(:File)-[:PART_OF]->(m:Module)
WHERE m.id IN $module_ids
RETURN p.id AS person_id, count(DISTINCT pr) AS prs
```

### Q11B

**Description:** Thread participation count component for who_knows expertise scoring

```cypher
MATCH (p:Person)-[:PARTICIPATED_IN]->(th:Thread)-[:MENTIONS]->(m:Module)
WHERE m.id IN $module_ids
RETURN p.id AS person_id, count(DISTINCT th) AS threads
```

### Q11C

**Description:** Authored decision count component for who_knows expertise scoring

```cypher
MATCH (d:Decision)-[:AFFECTS]->(m:Module), (d)-[:DECIDED_BY]->(p:Person)
WHERE m.id IN $module_ids
RETURN p.id AS person_id, count(DISTINCT d) AS decisions
```

### Q11D

**Description:** Person profile details (display name, role)

```cypher
MATCH (p:Person) WHERE p.id IN $ids RETURN p.id AS id, p.display AS display, p.role AS role
```

### Q12

**Description:** Recent PR changes touching a specific module

```cypher
MATCH (pr:PR)-[:TOUCHES]->(:File)-[:PART_OF]->(m:Module {id:$module_id})
WHERE pr.merged_at >= $since
RETURN DISTINCT pr.id AS id, pr.display AS title, pr.merged_at AS merged_at
ORDER BY merged_at DESC LIMIT $limit
```

### Q13

**Description:** Shortest connection path between any two graph nodes

```cypher
MATCH (a {id:$a}), (b {id:$b})
WITH shortestPath((a)-[*..6]-(b)) AS p
RETURN p
```

### Q14

**Description:** PageRank centrality calculation over person-to-person collaboration edges

```cypher
CALL algo.pageRank('Person', 'COLLABORATES_WITH') YIELD node, score
RETURN node.id AS id, node.display AS display, score
ORDER BY score DESC LIMIT $limit
```

### Q15A

**Description:** Find existing open review request for a decision

```cypher
MATCH (r:ReviewRequest {status:'open'})-[:REVIEWS]->(:Decision {id:$decision_id}) RETURN r.id AS id LIMIT 1
```

### Q15B

**Description:** Create new review request for a decision

```cypher
MATCH (d:Decision {id:$decision_id})
CREATE (r:ReviewRequest {id:$rr_id, display:$display, note:$note, status:'open', created_at:$now, source:'agent'})
CREATE (r)-[:REVIEWS]->(d)
RETURN r.id AS id
```

### Q15C

**Description:** Assign review request to the original decision author

```cypher
MATCH (r:ReviewRequest {id:$rr_id}), (:Decision {id:$decision_id})-[:DECIDED_BY]->(p:Person)
CREATE (r)-[:ASSIGNED_TO]->(p)
RETURN p.id AS person_id, p.display AS person
```

### Q16

**Description:** Derive collaboration edges between authors sharing touched modules

```cypher
MATCH (a:Person)-[:AUTHORED]->(:PR)-[:TOUCHES]->(:File)-[:PART_OF]->(m:Module)<-[:PART_OF]-(:File)<-[:TOUCHES]-(:PR)<-[:AUTHORED]-(b:Person)
WHERE a.id <> b.id
WITH a, b, count(DISTINCT m) AS shared
MERGE (a)-[c:COLLABORATES_WITH]->(b)
SET c.weight = shared
```

### Q17

**Description:** Overview subgraph containing decisions and their immediate neighbors

```cypher
MATCH (d:Decision)-[r]-(n) RETURN d, r, n LIMIT $limit
```

### Q18

**Description:** One-hop neighborhood subgraph around an arbitrary node

```cypher
MATCH (a {id:$id})-[r]-(n) RETURN a, r, n LIMIT $limit
```

### Q19

**Description:** Individual node detail with label and degree count

```cypher
MATCH (n {id:$id})
OPTIONAL MATCH (n)-[r]-()
RETURN n, labels(n)[0] AS label, count(r) AS degree
```

### Q20

**Description:** All review requests ordered by creation time with decision details

```cypher
MATCH (r:ReviewRequest)-[:REVIEWS]->(d:Decision)
OPTIONAL MATCH (r)-[:ASSIGNED_TO]->(p:Person)
RETURN r, d.id AS decision_id, d.display AS decision, collect(p.id) AS assignee_ids
ORDER BY r.created_at DESC
```

### Q21

**Description:** Simulate a merged demo PR touching a module

```cypher
MATCH (m:Module {id:$module_id})
MERGE (f:File {id:$file_id})
  SET f.path = $path, f.display = $path, f.source = 'synthetic', f.synthetic_demo = true
MERGE (f)-[:PART_OF]->(m)
CREATE (pr:PR {id:$pr_id, number:$number, display:$title, state:'merged', merged_at:$now,
               created_at:$now, source:'synthetic', synthetic_demo:true})
CREATE (pr)-[:TOUCHES]->(f)
RETURN pr.id AS id
```

### Q22A

**Description:** Demo reset: delete all synthetic demo PR and File nodes

```cypher
MATCH (n) WHERE n.synthetic_demo = true DETACH DELETE n
```

### Q22B

**Description:** Demo reset: delete all ReviewRequest nodes

```cypher
MATCH (r:ReviewRequest) DETACH DELETE r
```

### Q23

**Description:** Resolve codebase modules mentioned or affected by search hits

```cypher
MATCH (n)-[:MENTIONS|AFFECTS]->(m:Module) WHERE n.id IN $ids
RETURN DISTINCT m.id AS id, m.display AS display
```

### Q24

**Description:** Find current maximum demo PR number for sequence generation

```cypher
MATCH (pr:PR {synthetic_demo:true}) RETURN coalesce(max(pr.number), 899999) AS n
```

### Q25

**Description:** List all modules sorted by path with formal owning team

```cypher
MATCH (m:Module)
OPTIONAL MATCH (t:Team)-[:OWNS]->(m)
RETURN m.id AS id, m.display AS display, m.path AS path, t.display AS owner_team
ORDER BY m.path
```

### Q26

**Description:** Count of graph nodes grouped by label

```cypher
MATCH (n) RETURN labels(n)[0] AS label, count(*) AS n
```

### Q27

**Description:** Count of graph relationships grouped by relationship type

```cypher
MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS n
```

## Graph Algorithms: PageRank Centrality

Company Brain utilizes FalkorDB's native high-performance matrix algorithms to calculate contributor influence across the codebase collaboration graph.

### Procedure Signature

```cypher
CALL algo.pageRank('Person', 'COLLABORATES_WITH') YIELD node, score
RETURN node.id AS id, node.display AS display, score
ORDER BY score DESC LIMIT $limit
```

### Algorithm Mechanics
- **Target Graph:** Subgraph composed of `Person` nodes linked by bidirectional `COLLABORATES_WITH` relationships (derived in `Q16` based on shared module authorship).
- **Convergence:** Evaluates relative prestige/centrality across the network. Contributor scores reflect not merely PR volume, but the degree to which a contributor bridges different engineering groups and architectural domains.
- **Usage:** Powers the `key_connectors` tool and REST service to identify central domain experts and prevent institutional knowledge silos.
