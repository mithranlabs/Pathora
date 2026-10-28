# SignalFuse (AO-01) System Design

Oct 28, 2026 · @Mithran ninja

Build a deterministic, dependency-aware correlation pipeline with constrained clustering and ranked (not asserted) origins; add ML only if the dataset legitimately supports it.

## 1. Executive recommendation

Build **Architecture B**: score alert pairs with an interpretable weighted formula, cluster with average-linkage under hard time and dependency gates, and rank origins as hypotheses with an explicit "undetermined" outcome. Treat deterministic rules (A) as the baseline and the gate, and treat machine learning (C) as a P1 option that must win an ablation before it ships.

**Why B**

- At 400–900 alerts a day across \~70 services, compute is not the constraint. Precision on concurrent incidents and noisy labels is. A graded, inspectable score attacks that directly; hard rules cannot express partial evidence.
- Published incident-linking work combines text/attribute similarity with service-dependency information ([LiDAR](https://2020.esec-fse.org/details/fse-2020-papers/193/Identifying-Linked-Incidents-in-Large-Scale-Online-Service-Systems), [DiLink](https://arxiv.org/abs/2403.18639)). Those are trained deep models on proprietary Microsoft data. A linear score over the same signal families is a cheap test of the same idea. Whether it captures enough of the gain is an empirical question our ablations must answer.
- Every grouping can be shown as a feature breakdown, which is the strongest explainability story available without an LLM.

**Where I push back on the brief**

1. **"Notification reduction" is gameable.** Merging everything gives near-100% reduction. It is only reportable next to incident recall and a *swallow rate* (a real incident absorbed into another incident's cluster).
2. **The dependency map is soft evidence.** The Google SRE book reports [limited success with complex dependency hierarchies](https://sre.google/sre-book/monitoring-distributed-systems/) because infrastructure keeps changing. We weight it and ablate it, and use it as a hard rule only as a generous gate.
3. **Cross-source corroboration is not evidence on its own.** Two tools can fire on unrelated noise. We use it as a cluster-level confidence bonus, not a pair feature.
4. **Origin ranking is the riskiest claim.** We report it against no-skill baselines (earliest alert, highest severity, historical root-cause frequency). A frequency prior can look strong: one 2026 [preprint](https://arxiv.org/abs/2609.27069) found a telemetry-blind prior placed the true culprit in the top five on 99.7% of in-distribution RCAEval cases, because the benchmark injects faults into only five services per system.
5. **Do not engineer for scale we do not have.** All-pairs comparison inside a rolling window is cheap at this volume. Skip blocking/LSH, brokers and databases.
6. **ML is a leakage risk before it is an accuracy gain.** The number of labelled incidents is unknown. Any learning stays at logistic regression on pair features, with incident-grouped splits.

**Not building:** LLM dependencies, microservices, a message broker, or anything that suppresses, acknowledges or closes a live alert. Section 13 ends with the decision and the first five tasks.

## 2. Research review

No published benchmark matches this exact task, so none of the cited numbers transfer to our dataset. **Published** lines state what a source reports, based on the abstracts and excerpts I retrieved (I did not read every paper in full). **Implication** lines are my recommendations.

### 2.1 Rule-based and temporal correlation

- **Mechanism and assumptions:** group by label equality inside a time window; suppress by rule. Assumes labels consistently encode relatedness and someone maintains the rules.
- **Published:** Prometheus [Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/) groups alerts of similar nature into one notification, and its inhibition mutes alerts when a higher-level one is firing (for example, "cluster unreachable"). The SRE book separates [symptoms from causes](https://sre.google/sre-book/monitoring-distributed-systems/) and notes that one layer's symptom is another layer's cause. [Valdes and Skinner (RAID 2001)](https://www.csl.sri.com/papers/raid2001-pac/prob_corr.pdf) correlate alerts by feature overlap and similarity: a new alert joins the most similar "meta alert" above a minimum-match threshold, otherwise it starts a new one. They explicitly consider late reports and clock drift across heterogeneous sensors.
- **Strengths / weaknesses:** cheap and explainable, but binary, brittle at thresholds, and inhibition hides notifications.
- **Cost:** low. **Implication:** this is Architecture A and our gating layer. Valdes–Skinner is the closest published ancestor of our scoring-plus-threshold design.

### 2.2 Fingerprints and semantic similarity

- **Mechanism:** normalize volatile tokens into a template. [Drain](https://arxiv.org/abs/1806.04356) does this online with a fixed-depth parse tree. DiLink vectorizes incident text and categorical fields (title, topology, monitor id, failure type) with TF-IDF before learning embeddings.
- **Assumptions:** messages have stable templates, and anonymization did not destroy the tokens.
- **Weaknesses:** identical text does not mean the same incident (a chronically noisy rule), and the same incident can show different text across sources.
- **Cost:** regex masking is low; Drain is moderate. **Implication:** fingerprint = (source, service, normalized rule name), with TF-IDF cosine over template tokens as one feature. Skip neural sentence embeddings unless the data has rich free text; templated alerts rarely need them.

### 2.3 Alarm clustering and recurring root causes

- **Published:** [Julisch (ACM TISSEC 2003)](https://researcher.ibm.com/publications/clustering-intrusion-detection-alarms-to-support-root-cause-analysis) observed in intrusion-detection alarms that a few dozen persistent root causes account for over 90% of alarms. The general alarm-clustering problem is NP-complete, so he proposed an approximation.
- **Caveat:** security alarms, not SRE alerts. We must check whether our data has the same skew.
- **Implication:** compute each fingerprint's baseline firing rate in the training period. Chronic fingerprints carry little linking information, like a high-document-frequency word. This is a P1 feature (`f_chronic`) and doubles as a "noisiest rules" report.

### 2.4 Graph and dependency-aware incident linking

- **Published:** LiDAR (FSE 2020) combines incident text with structure from historical links over a component-dependency network. DiLink combines text and dependency-graph embeddings; on incidents from five Microsoft workloads (610 services) the authors [report an F1 of 0.96, a 14% gain over prior methods](https://www.microsoft.com/en-us/research/?p=1020150), and they study how graph completeness affects accuracy. [COLA](https://arxiv.org/abs/2403.06485) (ICSE-SEIP 2024) is a hybrid of correlation mining and LLM reasoning for online alert aggregation.
- **Assumptions:** a reasonably complete, current dependency graph; plentiful labelled links for the learned models.
- **Cost:** high for the learned embeddings, low for our weighted score. **Implication:** these validate the feature families (time, text/attributes, dependencies), not our expected accuracy.

### 2.5 Clustering algorithms

- **Published:** [correlation clustering](https://research.tue.nl/en/publications/correlation-clustering/) (Bansal, Blum, Chawla) partitions items to agree with +/− pairwise labels and needs no cluster count. [Ailon, Charikar and Newman (JACM 2008)](https://doi.org/10.1145/1411509.1411513) give a simple randomized Pivot algorithm with a constant-factor approximation on complete graphs. [DBSTREAM](https://rdrr.io/cran/stream/man/DSC_DBSTREAM.html) (Hahsler and Bolanos, IEEE TKDE 2016) keeps micro-clusters plus a shared-density graph for evolving streams.
- **Implication:** the design question is chaining. The comparison and choice are in section 6.

### 2.6 Root-cause localization versus correlation

- **Published:** [MonitorRank](https://doi.org/10.1145/2465529.2465753) (SIGMETRICS 2013) ranks candidate causes using metric time series plus the call graph. [MicroRCA](https://hal.archives-ouvertes.fr/hal-02441640) models anomaly propagation on an attributed graph of services and machines. [Pham et al. (ASE 2024)](https://arxiv.org/abs/2408.13729) evaluated nine causal-discovery and 21 RCA methods and found no method stands out in all situations, and that results on synthetic data may not reflect real systems. [RCAEval](https://arxiv.org/abs/2412.17015) offers 735 fault-injected failure cases across three systems. The SRE book says Google avoids "magic" systems that automatically detect causality.
- **Key distinction:** these methods consume metrics and traces. If we only have alerts, we solve a weaker problem: *origin ranking* from alert timing plus topology.
- **Implication:** output ranked hypotheses with an abstain option, and never present them as proven root causes.

### 2.7 Alert storms and noise reduction

- **Published:** [Zhao et al. (ICSE-SEIP 2020)](https://2020.icse-conferences.org/details/icse-2020-poster/24/Understanding-and-Handling-Alert-Storm-for-Online-Service-Systems) report storm detection with F1 above 0.9 and a storm summary that cut alerts to examine by over 98% on their data. Datadog [notes](https://www.datadoghq.com/blog/reduce-alert-storms-datadog) (vendor guidance) that callers alert when a dependency fails, which makes microservices prone to storms. The SRE book warns that frequent pages lead people to ignore a real one masked by noise. A 2026 industrial [preprint (AlertGuardian)](https://arxiv.org/abs/2601.14912) frames the problem across the whole alert life cycle, including rule refinement.
- **Implication:** large reduction is achievable on someone's data, and so is hiding a real signal. That is why we never suppress, and why swallow rate is a first-class metric.

### 2.8 Evaluation metrics and leakage

- **Published:** [Amigó et al. (2009)](https://doi.org/10.1007/s10791-008-9066-8) tested extrinsic clustering metrics against formal constraints and found only BCubed satisfied all of them. [Kapoor and Narayanan (Patterns 2023)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10499856/) surveyed leakage across 17 fields, built an eight-type taxonomy (including temporal leakage and illegitimate features), and showed in a case study that complex models lost their apparent edge once leakage was corrected.
- **Implication:** report BCubed alongside pairwise F1, split chronologically with purge gaps, and audit features for target leakage (section 9).

## 3. Architecture comparison

B wins on explainability and robustness per hour of work; A is the mandatory baseline; C is only justified if error analysis shows B is limited by hand-set weights. These are my assessments, not measured results.

| Criterion | A. Deterministic rules | B. Weighted graph + clustering | C. Hybrid with optional ML |
| --- | --- | --- | --- |
| What it is | Group by (service, rule) in a time window; inhibit via dependency rules; same-service cross-source merge | Gated pair scoring over time, dependency, fingerprint and symptom features; average-linkage clustering | B's features, with pair weights fit by logistic regression (or a small tree model) on training links |
| Accuracy potential | Good on obvious cascades; capped by hand-written rules | Medium to good; graded evidence handles partial matches | Highest if enough clean labelled links; unknown until we see the data |
| Main failure modes | Under-grouping when strict, over-grouping when loose; no uncertainty | Sensitive to weights and thresholds; hub dependencies cause chaining; stale topology | Leakage; overfitting on few incidents; drift; opaque when tree-based |
| Implementation complexity | Low | Medium | Medium-high (training loop, calibration, leakage controls) |
| Runtime and memory | Trivial | Small at this volume (all-pairs in a window) | Small for logistic regression; large for embeddings or deep models |
| Explainability | Highest: a named rule fired | High: per-edge feature breakdown | Medium: coefficients explain linear models, not trees or embeddings |
| Noisy, missing, delayed, contradictory alerts | Brittle: one missing label breaks a rule | Degrades gracefully: missing features contribute 0, time kernel tolerates delay | Learns tolerance if present in training data; otherwise fragile |
| Hackathon fit | Fast to a baseline, hard to impress | Best balance; features are independently ablatable | Risky unless the dataset is rich and a day or more remains |

**Decision:** implement A first as the evaluation baseline and as B's gate, ship B, and add C's logistic-regression weights as a P1 experiment using the same feature vector, so it costs no new architecture. Skip embeddings and LLM reasoning: the budget forbids paid APIs, and determinism is a stated requirement.

## 4. Recommended architecture

One run is a pipeline of four stages whose only output is files; the API and UI read those files and never write to any alerting tool.

&#91;embedded content: architecture · 4 pipeline stages, API, UI, evaluation lane\]

The dependency map feeds the gate and the origin ranker. Ground truth (dashed) enters only the evaluation harness, and stages 1 to 4 never read it.

### Batch sequence

## 5. Component responsibilities and data contracts

Correlation, clustering, origin ranking and explanation are four separate modules with typed hand-offs, so four agents can work in parallel against frozen contracts. All field names below are **assumptions** until the real schema is inspected (section 13).

| # | Component | Responsibility | Input → output | Must not |
| --- | --- | --- | --- | --- |
| 1 | Loader / normalizer | Parse files, UTC timestamps, canonical service ids, severity scale, null handling, schema validation | raw files → `alerts` table | Read ground-truth columns into feature code |
| 2 | Fingerprinter / burst builder | Template the alert name, compute the fingerprint, collapse flaps into bursts | `alerts` → `bursts` | Merge across services or sources |
| 3 | Dependency graph | Load the map, compute neighborhoods, upstream sets and node weights | dependency file → graph object | Learn edges from test-period incidents |
| 4 | Candidate generator | Emit only pairs inside the time window that pass the gate | `bursts` + graph → candidate pairs | Compare all alerts ever recorded |
| 5 | Feature extractor / scorer | Compute features and the weighted score with a per-feature breakdown | pairs → `edges` | Use severity, incident ids or resolution times as features |
| 6 | Clusterer | Average-linkage clustering with a span cap, then cohesion and bridge checks | `edges` → `clusters` | Drop any alert; every alert is assigned exactly once |
| 7 | Origin ranker | Score candidate services and decide whether to abstain | `clusters` + graph → `origins` | Claim a proven root cause or use severity as a signal |
| 8 | Confidence / uncertainty | Tier clusters, mark tentative merges, list unattached alerts | clusters + edges → tiers | Present uncalibrated scores as probabilities |
| 9 | Evidence store / explainer | Persist per-edge and per-origin evidence; render text from templates | all of the above → `evidence` | Call an external LLM |
| 10 | API | Serve runs read-only; trigger deterministic runs | run artifacts → JSON | Write back to any alerting tool |
| 11 | Frontend | Incident list, detail (timeline, subgraph, evidence), unattached lane, metrics | API → UI | Hide critical alerts when a cluster is collapsed |
| 12 | Evaluation harness | Metrics, splits, baselines, ablations, bootstrap CIs | predictions + ground truth → report | Run before the split manifest is frozen |

**Contracts (illustrative field names)**

```python
class Alert:            # one row per raw alert after normalization
    alert_id: str
    ts: int             # epoch seconds, UTC
    ts_end: int | None  # resolution time if provided; NEVER used as a feature in replay mode
    source: str
    service: str        # canonical id, may be "UNKNOWN"
    severity: str       # display only
    name: str           # raw rule or alert name
    text: str | None
    tags: dict[str, str]
    # ground truth lives in a separate table, joined only by the evaluation harness

class Burst:            # fingerprint-collapsed flaps
    burst_id: str
    fingerprint: str    # hash(source, service, template(name))
    onset: int
    last_seen: int
    alert_ids: list[str]
    service: str
    source: str
    symptom_class: str  # availability | error | latency | saturation | other

class Edge:             # candidate pair that survived the gate
    a: str
    b: str
    score: float        # 0..1, a link strength, not a probability
    features: dict[str, float]   # f_time, f_graph, f_shared, f_fp, f_sym
    gate: dict[str, float]       # dt_seconds, graph_distance, text_similarity

class Cluster:
    cluster_id: str
    burst_ids: list[str]
    alert_ids: list[str]         # every raw alert, each appears in exactly one cluster
    onset: int
    last_seen: int
    services: list[str]
    sources: list[str]
    max_severity: str            # always surfaced, even when collapsed
    cohesion: float              # mean intra-cluster edge score, missing pairs count as 0
    bridge_burst_ids: list[str]  # members whose removal disconnects the cluster
    tier: str                    # high | medium | low | tentative

class OriginCandidate:
    cluster_id: str
    service: str
    rank: int
    score: float
    components: dict[str, float] # e_time, e_cover, e_cons, e_ptr, e_prior
    supporting_alert_ids: list[str]
    verdict: str                 # candidate | undetermined
```

The evaluation harness consumes one file, `predictions.csv` with columns `alert_id, cluster_id` (plus optional `origin_service`), so any variant, baseline or ablation plugs in identically.

## 6. Correlation algorithm and pseudocode

The algorithm is five deterministic stages: collapse flaps into bursts, generate gated candidate pairs, score them, cluster with average-linkage, then rank origins. Every parameter value below is a **starting guess to be replaced by tuning**, not a result.

### 6.1 Normalization, fingerprints and bursts

1. Convert timestamps to UTC epoch seconds; map each service to a dependency-graph node (unmapped services become `UNKNOWN`, which scores 0 on graph features instead of failing).
2. Template the alert name: lowercase, then mask numbers, UUIDs, hosts and IPs.
3. Fingerprint = hash(source, service, template). Alerts with the same fingerprint and a gap of at most `g_flap` merge into one **burst** (onset = first alert, count = n).
4. Before building anything else, compute the **burst purity ceiling** on training data: the best pairwise recall any clustering could reach if bursts are atomic. If bursts mix incidents, lower `g_flap` or drop the collapse.

### 6.2 Candidate pairs

Sort bursts by onset. For each burst `i`, consider later bursts `j` with `0 ≤ t_j − t_i ≤ W` that pass the gate: `d(s_i, s_j) ≤ D` in the undirected dependency graph, **or** text similarity `f_fp ≥ θ_fp`. Index bursts by service and keep precomputed BFS neighborhoods. At this volume the gate exists mainly to cut false edges, not to save time.

### 6.3 Features (each in \[0, 1\])

```latex
f_{time}=e^{-|t_i-t_j|/\tau}\qquad f_{graph}=\gamma^{\,d(s_i,s_j)}\ (1\ \text{if same service, 0 if no path})
```

```latex
f_{shared}=\frac{\sum_{u\in U_i\cap U_j}w_u}{\sum_{u\in U_i\cup U_j}w_u},\qquad w_u=\max\!\Big(0,\ln\frac{N}{1+|D(u)|}\Big)
```

- `U_i` = the service plus everything it depends on within `k` hops. `D(u)` = services that depend on `u`. The weight `w_u` is IDF-like: a hub that everything depends on (auth, database) gets weight near 0, which blunts chaining through shared infrastructure.
- `f_fp` = 1 for an identical fingerprint, else TF-IDF cosine over template tokens (IDF fit on the training period only).
- `f_sym` = entry of a small symmetric compatibility table over symptom classes (availability, error, latency, saturation, other), derived from keywords in the rule name. Diagonal = 1, plausible cause-to-effect pairs such as saturation–latency around 0.7–0.8, anything with "other" around 0.3. This is an assumption to ablate.
- P1 candidates: `f_chronic` (down-weight chronically firing fingerprints) and historical co-occurrence of fingerprints from training incidents only.

### 6.4 Pair score

```latex
s_{ij}=g_{ij}\sum_k w_k f_k,\quad \sum_k w_k=1,\quad g_{ij}=\mathbb{1}[|\Delta t|\le W]\cdot\mathbb{1}[d\le D\ \lor\ f_{fp}\ge\theta_{fp}]
```

| Parameter | Starting value | Role |
| --- | --- | --- |
| `w_time, w_graph, w_shared, w_fp, w_sym` | 0.30, 0.25, 0.10, 0.25, 0.10 | Feature weights, sum to 1 |
| `W` / `τ` | 15 min / 300 s | Gate window / time-kernel scale |
| `D` / `γ` | 2 hops / 0.6 | Gate distance / graph decay |
| `θ_fp` | 0.6 | Text-similarity override of the graph gate |
| `g_flap` | 10 min | Burst collapse gap |
| `θ_edge` / `θ_cut` | 0.20 / 0.45 | Keep edge / stop merging |
| `T_max` | 4 h | Cluster span cap |

### 6.5 Clustering and why average-linkage

Split the edge graph (`s ≥ θ_edge`) into connected components, then run **average-linkage agglomerative clustering** inside each component, treating absent pairs as similarity 0. Merge the best pair of clusters while their mean pairwise similarity is at least `θ_cut`. A cluster that exceeds `T_max` is split at its largest time gap. With `scipy`, use `linkage(method='average')` on `1 − S` and cut at `1 − θ_cut`. Components are small, so the cost is negligible.

| Algorithm | Chaining risk | Uses "not related" evidence | Needs k | Verdict (my assessment) |
| --- | --- | --- | --- | --- |
| Connected components / single-link | High | No | No | Baseline only, to demonstrate chaining |
| Density-based (DBSCAN family) | Medium | Partly | No | Not chosen: one radius must serve both time and graph distance |
| Modularity community detection (Louvain/Leiden) | Low–medium | Via a null model | No | Optional ablation; extra dependency, not reviewed here |
| **Average-linkage** | **Low** | **Yes, absent pairs count as 0** | **No** | **P0 choice** |
| Correlation clustering (Pivot + local search) | Low | Yes, explicit | No | P1 ablation; theory in Ailon et al. |
| Incremental meta-alert assignment | Medium, order-dependent | Partly | No | P1 for replay and time-to-surface |

### 6.6 Defenses against transitive chaining and false merges

- Hard gate on time and dependency distance, so distant alerts never form edges.
- IDF-style weights on shared dependencies (hub penalty).
- Average-linkage instead of single-link: a long chain has low mean similarity.
- Span cap `T_max`, and cohesion reported for every cluster.
- **Bridge detection:** members whose removal disconnects the cluster edge graph are listed as ambiguous, and clusters with bridges are demoted to `tentative`.
- Concurrent-incident check: when two clusters overlap in time and share a hub, show both and the strongest cross-edge instead of merging silently.

### 6.7 Probable-origin ranking

Candidates are the services that have at least one burst in the cluster. For candidate `u`, with `S` the cluster's services and `d↓(u, v)` the length of the shortest dependency path from `v` to `u` (u is upstream of v):

```latex
e_{time}(u)=e^{-(t_u-t_{min})/\tau_o},\quad e_{cover}(u)=\frac{1}{|S|-1}\sum_{v\ne u}\gamma^{\,d_\downarrow(u,v)},\quad e_{cons}(u)=\frac{|\{v:\ u\to v,\ t_u\le t_v+\delta\}|}{|\{v:\ u\to v\}|}
```

```latex
r(u)=\lambda_{time}e_{time}+\lambda_{cover}e_{cover}+\lambda_{cons}e_{cons}+\lambda_{ptr}e_{ptr}\ [+\lambda_{prior}e_{prior}]
```

- `e_ptr` (pointing): share of other alerts whose text names `u` as the failing dependency. Only if the data has such text; otherwise drop the term and renormalize.
- `e_prior` (P1): smoothed frequency of `u` as a recorded root cause in **training-period** incidents only.
- Starting `λ`: time 0.25, cover 0.40, consistency 0.20, pointing 0.15. `δ` ≈ 60 s absorbs clock skew.
- **Severity is never a feature.** It is displayed, and used only as a baseline to beat.
- **Abstain** (`verdict = undetermined`, top 3 shown as candidates) when `r(1) < θ_o` or the margin `r(1) − r(2) < δ_m`.
- P1: list *shared dependencies with no alerts* that would explain many alerting services, labeled "topology inference, possible monitoring gap". An upstream-looking service is a hypothesis, not a cause.

### 6.8 Thresholds, tuning, insufficient evidence

- Tune `W, τ, D, γ, weights, θ_edge, θ_cut, g_flap` on the validation split by random search, with a pre-registered objective: maximize BCubed F1 subject to a swallow-rate limit and an incident-recall floor.
- Report the whole Pareto curve over `θ_cut` (notification reduction versus incident recall). Pick the simplest configuration within one standard error of the best, using incident-grouped bootstrap.
- P1: fit the weights by logistic regression on candidate pairs (label = same ground-truth incident, class-weighted) using the training split, and compare against hand-set weights on validation.
- **Insufficient evidence:** a burst with no edge above `θ_edge` stays a singleton in the *Unattached* lane. A low-cohesion cluster is `tentative` and links to its nearest alternative cluster. An origin with a thin margin is `undetermined`.

### 6.9 Pseudocode

```python
def run(alerts, graph, cfg):
    alerts = normalize(alerts)                          # UTC, canonical service ids
    bursts = build_bursts(alerts, cfg.g_flap)           # fingerprint + flap collapse
    idf = fit_idf(bursts_in_training_period)            # no labels used
    edges = []
    for i in sorted(bursts, key=onset):
        for j in candidates_after(i, bursts, cfg.W):    # time-indexed lookup
            d = graph.dist(i.service, j.service, cap=cfg.D)
            fp = text_sim(i, j, idf)
            if d is None and fp < cfg.theta_fp:         # gate
                continue
            f = {"time": exp(-abs(i.onset - j.onset) / cfg.tau),
                 "graph": cfg.gamma ** d if d is not None else 0.0,
                 "shared": idf_jaccard(graph.upstream(i.service),
                                       graph.upstream(j.service)),
                 "fp": 1.0 if i.fingerprint == j.fingerprint else fp,
                 "sym": SYM[i.symptom_class][j.symptom_class]}
            s = sum(cfg.w[k] * f[k] for k in f)
            if s >= cfg.theta_edge:
                edges.append(Edge(i, j, s, f))
    clusters = []
    for comp in connected_components(bursts, edges):
        clusters += average_link(comp, edges, cfg.theta_cut)
    clusters = [split_at_largest_gap(c) if span(c) > cfg.T_max else c
                for c in clusters]
    assert every_alert_assigned_exactly_once(clusters, alerts)   # invariant
    for c in clusters:
        c.cohesion = mean_pair_score(c, edges)          # absent pairs = 0
        c.bridges = articulation_points(c, edges, cfg.theta_edge)
        c.tier = tier(c)
        c.origins = rank_origins(c, graph, cfg)         # may return "undetermined"
    return clusters, edges
```

## 7. API endpoints

The API is read-only with respect to any alerting system: it computes and serves analysis, and it has no acknowledge, close or suppress endpoint. For P0, a run is computed synchronously and cached in memory; with a few hundred to a few thousand alerts that is seconds, not minutes (to be confirmed against the real data).

| Method and path | Purpose | Phase |
| --- | --- | --- |
| `GET /api/health` | Liveness and code/config hash | P0 |
| `POST /api/runs` | Run the pipeline on a split or time window with a config; returns `run_id` and a summary | P0 |
| `GET /api/runs/{run_id}` | Run manifest: config, data hash, git SHA, seed, stage timings | P0 |
| `GET /api/runs/{run_id}/incidents` | Cluster list with tier, size, services, onset, max severity; filters `tier`, `min_size`, `q` | P0 |
| `GET /api/runs/{run_id}/incidents/{cluster_id}` | Detail: alerts, timeline, origin candidates, evidence, bridges, nearest alternative cluster | P0 |
| `GET /api/runs/{run_id}/unattached` | Alerts that joined no cluster, never hidden | P0 |
| `GET /api/runs/{run_id}/alerts/{alert_id}/links` | "Why linked?": neighbor edges with feature breakdown | P1 |
| `GET /api/runs/{run_id}/metrics` | Metrics versus ground truth with baselines and CIs (only for labelled splits) | P0 |
| `GET /api/graph/services` | Dependency graph (nodes, directed edges) | P0 |
| `POST /api/runs/{run_id}/replay` | Step the clock and report when each incident first surfaced | P1 |
| `POST /api/alerts/batch` | Demo of batch ingestion: assign a posted batch to clusters without persisting | P2 |

**Example: `POST /api/runs`** (illustrative values, not from the dataset)

```json
{
  "split": "validation",
  "window": {"start": "2025-01-01T00:00:00Z", "end": "2025-01-08T00:00:00Z"},
  "config": {"W": 900, "tau": 300, "D": 2, "gamma": 0.6, "theta_cut": 0.45,
             "weights": {"time": 0.30, "graph": 0.25, "shared": 0.10, "fp": 0.25, "sym": 0.10}}
}
```

```json
{
  "run_id": "r_2025_001",
  "summary": {"alerts": 0, "bursts": 0, "clusters": 0, "unattached": 0,
              "notifications": 0, "reduction": 0.0},
  "manifest": {"git_sha": "<sha>", "data_hash": "<hash>", "seed": 7}
}
```

**Example: `GET /api/runs/{run_id}/incidents/{cluster_id}`** (shape only; every value is a placeholder)

```json
{
  "cluster_id": "c_0042",
  "tier": "medium",
  "onset": "2025-01-03T09:12:05Z",
  "last_seen": "2025-01-03T09:41:50Z",
  "services": ["svc-a", "svc-b", "svc-c"],
  "sources": ["tool-1", "tool-2"],
  "max_severity": "critical",
  "cohesion": 0.0,
  "bridge_burst_ids": [],
  "alerts": [{"alert_id": "a_1", "ts": "2025-01-03T09:12:05Z", "service": "svc-a",
              "severity": "warning", "source": "tool-1", "name": "..."}],
  "origin": {
    "verdict": "candidate",
    "candidates": [
      {"service": "svc-a", "rank": 1, "score": 0.0,
       "components": {"e_time": 0.0, "e_cover": 0.0, "e_cons": 0.0, "e_ptr": 0.0},
       "supporting_alert_ids": ["a_1"]}
    ],
    "caveat": "Ranked hypothesis from alert timing and topology; not a proven root cause."
  },
  "strongest_cross_cluster_edge": {"cluster_id": "c_0043", "score": 0.0},
  "explanations": ["svc-b joined because it depends on svc-a (distance 1) and fired 43 s later."]
}
```

Explanation strings are generated from templates over the stored feature values, so they are reproducible and cannot drift from the numbers.

## 8. Data model

P0 needs no database. Each run writes immutable files, and the API loads them into memory. SQLite earns a place only for analyst feedback (P2), because feedback is the one thing that must outlive a run.

```text
data/
  raw/                      # supplied files, never modified
  interim/alerts.parquet    # normalized alerts
  interim/ground_truth.parquet   # alert_id -> incident_id(s); read ONLY by the evaluation harness
  splits/split_manifest.json     # frozen: incident ids and time ranges per split, purge gaps
runs/<run_id>/
  manifest.json             # config, git sha, data hash, seed, stage timings, invariant checks
  bursts.parquet
  edges.parquet             # a, b, score, f_time, f_graph, f_shared, f_fp, f_sym, gate columns
  clusters.parquet          # cluster fields plus tier
  cluster_members.parquet   # cluster_id, burst_id, alert_id
  origins.parquet           # cluster_id, service, rank, score, e_* components, verdict
  evidence.jsonl            # one explanation record per edge and per origin candidate
  predictions.csv           # alert_id, cluster_id (+ origin_service) for the evaluation harness
  metrics.json              # when ground truth is available
```

| Table | Key | Notes |
| --- | --- | --- |
| `alerts` | `alert_id` | Display fields plus normalized timestamp and service; no ground-truth columns |
| `bursts` | `burst_id` | Fingerprint, onset, last seen, member alert ids |
| `edges` | `(a, b)` | Only gated pairs above `θ_edge`; feature columns kept for explanation and for fitting weights |
| `clusters` / `cluster_members` | `cluster_id` | Every alert appears exactly once; invariant checked at write time |
| `origins` | `(cluster_id, service)` | Includes `verdict` and component scores |
| `ground_truth` | `alert_id` | May be one-to-many if alerts can link to several incidents (to confirm) |

If SQLite is added for feedback: one table `feedback(run_id, cluster_id, alert_id, verdict, note, created_at)`, with no foreign keys into live systems.

## 9. Evaluation methodology and experiment plan

Evaluate on the supplied ground truth only, with incident-grouped chronological splits, one report format for every variant, and no result claimed until it is measured. Synthetic data may appear in unit tests and clearly labeled demos, never in the reported numbers.

### 9.1 Metrics

| Metric | Definition | Pitfall to control |
| --- | --- | --- |
| Pairwise P / R / F1 | Over unordered alert pairs: a pair is positive if both alerts share a ground-truth incident | Big incidents dominate (pairs grow quadratically); report micro and per-incident macro |
| [BCubed](https://doi.org/10.1007/s10791-008-9066-8) P / R / F1 | Per-alert precision and recall of its cluster-mates, averaged over alerts | Needs an extension if alerts can belong to several incidents |
| Incident recovered / swallowed / fragmented | Recovered: some cluster covers ≥ 50% of the incident and ≥ 50% of that cluster is the incident. Swallowed: coverage ≥ 50% but the cluster is < 50% that incident. Fragmented: no cluster covers ≥ 50% | The 50% cutoffs are conventions; fix them before seeing results |
| Incident recall | Share of ground-truth incidents recovered | Must be read together with swallow rate |
| Notification reduction | 1 − (clusters + unattached) / raw alerts | Gameable; never report alone. Also report notifications per true incident |
| False merges / false splits | Impure-cluster rate (clusters with alerts from ≥ 2 incidents); mean clusters per incident | Attribute each error to a gate, a feature or the clustering step in error analysis |
| Visibility invariant | Count of alerts missing from the output | Must be exactly 0 on every run |
| Time to surface | Replay metric, section 9.5 | Must use only alerts with `ts` ≤ the replay clock |
| Origin top-1 / top-3, selective accuracy | Match to the recorded root-cause service; accuracy among non-abstained clusters, plus abstention rate | Compare with baselines in 9.4; exact definition of a correct origin depends on the incident records |
| Calibration (if supported) | Reliability curve and ECE for pair score or tier versus empirical purity | Only with enough labelled pairs per bin; otherwise label scores "uncalibrated" |

### 9.2 Splits and leakage control

- **Chronological and incident-grouped.** Default 60/20/20 by incident start time (adjust if validation has too few incidents). An incident goes to one split whole. Unmatched alerts follow their timestamp.
- **Purge gap.** Around each boundary, exclude from scoring any alert within (maximum incident duration + `W`) of the boundary, so an incident cannot straddle splits.
- **Tuning** uses rolling-origin validation inside the training period. The test split is run once, after configuration freeze, and the number of configurations tried is logged.
- **Leakage audit** (taxonomy from [Kapoor and Narayanan](https://pmc.ncbi.nlm.nih.gov/articles/PMC10499856/), who list temporal leakage and illegitimate features among the types):
  1. No feature derived from incident ids, incident start/end, root-cause fields, or "alert falls inside an incident window".
  2. `ts_end` and any other after-the-fact field are unavailable in replay.
  3. IDF, chronic-fingerprint rates, co-occurrence tables and root-cause priors are fit on training data only.
  4. Dependency edges inferred from incident links use training-period incidents only.
  5. Check text fields for strings that encode incident ids or postmortem tags.
  6. Recurring incidents are legitimate history only if the earlier occurrence precedes the later one in time; no random splits.
  7. Feature code cannot import the ground-truth table (enforced by a test).

### 9.3 Hard cases

- **Overlapping incidents:** stratify results by whether the incident overlaps another in time. This is where false merges concentrate.
- **Alerts linked to several incidents:** use the overlapping extension of BCubed from Amigó et al., or report a single-label subset and the multi-label remainder separately.
- **Unmatched alerts:** report two variants. *Strict*: each unmatched alert is its own class, so attaching it to an incident counts as an error. *Lenient*: pairs of unmatched alerts are ignored. Also report the contamination rate (unmatched alerts attached to incident clusters).
- **Class imbalance:** pairs are overwhelmingly negative, so no accuracy; use P/R/F1 and per-incident macro averages.
- **Ambiguous or noisy labels:** manually audit a fixed random sample of disagreements (for example the 20 worst per split) and say how many looked like label errors. Treat any score as bounded by label quality.

### 9.4 Baselines and diagnostics

| ID | Baseline or diagnostic | Purpose |
| --- | --- | --- |
| B0 | No grouping: every alert is a notification | Floor |
| B1 | Fingerprint dedup: same (service, template) within a gap | Alertmanager-style grouping |
| B2 | Gap sessionization: chain alerts with gap ≤ g | Shows temporal chaining |
| B3 | Architecture A: rules plus dependency inhibition | The rule-based comparator |
| D1 | Burst purity ceiling | Best recall if bursts are atomic |
| D2 | Gate recall ceiling | Share of same-incident pairs that pass the gate; bounds recall of every later stage |
| O1–O4 | Origin baselines: earliest alert's service, highest-severity alert's service, training-period root-cause frequency, random service in the cluster | No-skill references for origin ranking |

### 9.5 Time to surface (replay)

Advance a clock in 60 s ticks. At each tick, cluster only alerts with `ts` ≤ clock. For each ground-truth incident, record the first tick at which a cluster holds ≥ 2 of its alerts from ≥ 2 services and is ≥ 80% that incident. Report the median and p90 of (surface time − first alert time) against B1 and B2, plus compute time per tick separately. Any use of future alerts is a leak.

### 9.6 Experiment table

Results stay `TBD` until measured. "Keep if" is the pre-registered decision rule.

| ID | Question | Change versus previous | Primary metric | Keep if | Result |
| --- | --- | --- | --- | --- | --- |
| E0 | Floor and ceilings | B0, B1, B2, D1, D2 | All | Always report | TBD |
| E1 | Does the gate plus time kernel beat the baselines? | A with gate and `f_time` only | BCubed F1, swallow rate | Better than B1/B2 with CI above 0 | TBD |
| E2 | Does a text/fingerprint feature help? | Add `f_fp` | BCubed F1 | Paired gain CI above 0, swallow not worse | TBD |
| E3 | Does the dependency graph help? | Add `f_graph`, `f_shared` | BCubed F1 on overlapping and cross-service incidents | Same rule | TBD |
| E4 | Does the symptom table help? | Add `f_sym` | BCubed F1 | Same rule; otherwise drop | TBD |
| E5 | Clustering choice | Single-link, average-link, Pivot | BCubed F1, swallow rate | Lowest swallow at equal F1 | TBD |
| E6 | Is the hub weight useful? | Remove IDF weight in `f_shared` | False-merge rate | Keep if removal worsens it | TBD |
| E7 | Burst collapse | With and without bursts | F1, runtime | Keep if purity ceiling stays high | TBD |
| E8 | Hand weights versus logistic regression | Fit weights on training | BCubed F1 on validation | Gain CI above 0 on validation, then confirmed on test | TBD |
| E9 | Origin ranking versus baselines | O1–O4 versus `r(u)` | Top-1, top-3, selective accuracy | Beats the best no-skill baseline | TBD |
| E10 | Origin term ablations | Remove `e_time`, `e_cover`, `e_cons`, `e_ptr` | Top-3 | Keep terms that help | TBD |
| E11 | Robustness | Drop 10–20% of alerts, jitter timestamps, remove or add topology edges | Change in F1 and swallow rate | Degradation reported either way | TBD |
| E12 | Time to surface | Replay versus B1/B2 | Median, p90 | Report either way | TBD |

### 9.7 Statistics and the complexity rule

- Resample **incidents**, not alerts, for bootstrap confidence intervals (alerts inside one incident are not independent), and compare variants with paired per-incident differences.
- A component stays only if (a) its paired gain has a 95% interval above zero on validation, (b) swallow rate does not worsen, and (c) the gain survives the single test run. Otherwise remove it, even if it was fun to build.
- Report the total number of configurations tried, so readers can judge selection bias.
- Confidence calibration is attempted only if validation has enough labelled pairs per score bin. If not, tiers stay ordinal and the UI says "uncalibrated".

## 10. Security, privacy, failure modes and observability

The system is read-only analysis. It never touches a live alerting tool, never calls an external service, and never hides an alert.

### 10.1 Security and privacy

- **Read-only by design:** no acknowledge, close, suppress or write-back endpoints. Alerts are always reachable from the incident view, and the *Unattached* lane lists everything that did not cluster.
- **Critical alerts stay visible:** a collapsed cluster still shows its max severity and its count of critical alerts. A cluster cannot be labeled "noise".
- **No external calls:** all processing is local, and there is no LLM or telemetry. The dataset is anonymized; do not attempt to re-identify services, and keep supplied ids as given.
- **Redaction toggle:** if free text exists, mask emails, IPs and hostnames before display and before writing logs. Logs carry ids and numbers, never raw alert text.
- **Hygiene:** pin dependency versions, restrict CORS to the dev origin, keep `data/raw` out of git if the terms require it, and treat uploaded files as untrusted input (size limit, schema validation, no `eval`, no pickle).

### 10.2 Failure modes

| Failure | Symptom | Mitigation | How to test |
| --- | --- | --- | --- |
| Concurrent incidents share a hub dependency | One mega-cluster; a small real incident swallowed | Hub-weighted `f_shared`, average-linkage, span cap, cross-cluster edge shown | Overlap-stratified metrics; swallow rate |
| Stale or incomplete dependency map | Related services never link, or false links | Text and time features can link without the graph (`θ_fp` override); graph weight tuned; edge-perturbation experiment | E11 |
| Late, delayed or out-of-order alerts | Onset order misleads origin ranking | Soft time kernel; tolerance `δ`; origin abstains on thin margins | Timestamp jitter in E11 |
| Clock skew across sources | Cause appears after its effect | `δ` tolerance; report skew if estimable from same-fingerprint alerts | Synthetic unit test, labeled as such |
| Flapping alerts | Hundreds of near-duplicates | Burst collapse with `g_flap`; purity ceiling check | E7, D1 |
| Monitoring outage fires many unrelated alerts | One cluster of non-causal alerts | Chronic-fingerprint down-weight (P1); tier stays `tentative` if cohesion is low | Inspect any very large cluster |
| Contradictory or duplicated alerts across sources | Same event with two severities | Fingerprint includes source; cluster-level corroboration bonus only | Unit test on duplicates |
| Missing fields (service, text) | Features undefined | Missing contributes 0 and is recorded in the evidence; no crash | Schema-validation tests |
| Non-determinism | Runs differ | Fixed seed, stable sort keys, hash of config and data in the manifest | Same config twice gives identical `predictions.csv` |
| Label noise or missing links | Metrics understate or overstate | Manual audit of disagreements; caveat on every metric slide | Audit sample in 9.3 |
| Origin presented as truth | Overconfident UI | Abstain rule; "ranked hypothesis" caveat string in every origin payload | UI review |

### 10.3 Observability

- **Run manifest:** git SHA, config hash, data hash, seed, per-stage timings, row counts in and out of each stage.
- **Invariants** (fail the run, not just warn): every alert in exactly one cluster; no duplicated ids; scores in \[0, 1\]; weights sum to 1; no ground-truth column read by feature code.
- **Health indicators per run:** cluster-size distribution, size of the largest cluster, share of unattached alerts, edge density, gate-pass rate, tier counts, abstention rate.
- **Structured JSON logs** with run id and stage; no alert text.
- **Golden tests:** a small, hand-checked fixture whose clusters and origin ranking must not change unless a test is updated on purpose.

## 11. P0 / P1 / P2 implementation roadmap

Total time is unknown, so the budget is in percentages with two worked examples. P0 plus P1 consume 75%; **25% is reserved** for integration, testing and demo (the brief requires at least 20%). Freeze features when that reserve begins.

| Workstream | Share | If 24 h | If 48 h |
| --- | --- | --- | --- |
| Recon, contracts, split manifest | 10% | 2.4 h | 4.8 h |
| Evaluation harness and baselines | 15% | 3.6 h | 7.2 h |
| Core pipeline (bursts, gate, features, clustering) | 20% | 4.8 h | 9.6 h |
| API and frontend (P0) | 15% | 3.6 h | 7.2 h |
| P1 differentiators | 15% | 3.6 h | 7.2 h |
| Integration, testing, demo preparation | 25% | 6.0 h | 12.0 h |
| **Total** | **100%** | **24.0 h** | **48.0 h** |

### P0: minimum viable end-to-end system

| ID | Task | Depends on | Acceptance criteria | Main risk |
| --- | --- | --- | --- | --- |
| T0.1 | Read the rubric, profile the data, freeze contracts and splits | none | `DATA_REPORT.md`, `contracts.md` and `split_manifest.json` committed; open questions (section 13) answered or logged | Schema or rubric surprises |
| T0.2 | Loader and normalizer with validation | T0.1 | `alerts.parquet` written; schema tests pass; ground truth stored separately | Messy timestamps or service ids |
| T0.3 | Evaluation harness plus baselines B0–B2, D1 | T0.1 (fixtures), T0.2 (real data) | Metrics match hand calculations on a tiny fixture; validation numbers for B0–B2; visibility invariant enforced | Metric bugs that look plausible |
| T0.4 | Bursts, gate, features, scoring, average-linkage clusters | T0.2 | Deterministic `predictions.csv` on validation; D2 gate recall reported; compared with B1/B2 | Chaining, weights untuned |
| T0.5 | Origin ranker v0 and baselines O1–O4 | T0.4 | `origins.parquet` with abstain logic; origin metrics against incident records | Root-cause field is free text or fuzzy |
| T0.6 | API P0 endpoints | T0.1 (mock JSON), T0.4 (real run) | Responses validate against the schemas in section 7; contract tests pass | Contract drift |
| T0.7 | Frontend P0: incident list, detail (timeline, dependency subgraph, origin with caveat), unattached lane, metrics tab | T0.6 (mocks) | Renders a real run; no console errors in Chrome DevTools; max severity visible on collapsed clusters | Time sink on styling |
| T0.8 | Integration checkpoint | T0.4–T0.7 | One command goes from raw files to UI on validation; manifest invariants pass | Late integration surprises |

### P1: differentiators with measurable value

| ID | Task | Depends on | Acceptance criteria |
| --- | --- | --- | --- |
| T1.1 | Tiers, bridge detection, tentative flags, nearest alternative cluster | T0.4 | Every cluster has a tier and an explanation; bridge list verified on a hand-checked case |
| T1.2 | Evidence store and templated "why linked?" explanations | T0.4 | Explanation text is generated only from stored feature values |
| T1.3 | Tuning loop, Pareto curve, incident-bootstrap CIs, ablations E1–E7 | T0.3, T0.4 | Experiment table filled with measured values and the keep/drop decision |
| T1.4 | Replay mode and time to surface (E12) | T0.4 | No future-alert use, verified by a test that shuffles future alerts |
| T1.5 | Robustness tests (E11) | T1.3 | Degradation curves reported |
| T1.6 | Pivot correlation clustering (E5) | T1.3 | Comparison against average-linkage on identical inputs |
| T1.7 | Logistic-regression weights (E8) | T1.3 | Only if validation has enough labelled incidents; evaluated on the untouched test split once |
| T1.8 | Origin extras: `e_ptr`, `e_prior`, shared-dependency note (E9–E10) | T0.5 | Beats the best no-skill origin baseline, or the doc says it does not |

### P2: optional polish

- Noisiest-fingerprint report to support alert-rule refinement (follows the life-cycle framing in the AlertGuardian preprint).
- Weight sliders in the UI to demonstrate sensitivity.
- Analyst feedback with SQLite, and CSV/JSON export.
- Personalized PageRank on the reversed dependency graph as an origin ablation.
- UI polish, README with the diagrams, scripted demo, and a recorded fallback.

### Parallelization and interfaces

**Freeze before any parallel work (end of T0.1):** the normalized alert schema, the split manifest, the `predictions.csv` contract, the `Edge`/`Cluster`/`OriginCandidate` shapes, the API JSON schemas, the feature function signature `f(burst_i, burst_j, ctx) -> dict[str, float]`, the run directory layout, and one YAML config schema. One owner approves any contract change.

| Track | Scope | Can run in parallel because |
| --- | --- | --- |
| A | Loader, evaluation harness, baselines | Works from fixtures, then real data |
| B | Fingerprints, features, clustering, origin ranking | Consumes the alert schema, emits `predictions.csv` |
| C | API and frontend | Builds against mock JSON that matches the frozen schemas |

**Not parallel:** threshold tuning (needs A and B), the final single test-split run (one owner), and contract changes.

**Tooling:** one Antigravity agent per track on its own git branch or worktree. Kiro writes each track's spec with acceptance criteria and later reviews and QAs merges. Context7 supplies current FastAPI, pandas, NetworkX and SciPy documentation. Chrome DevTools MCP checks the running UI (console, network payloads, layout). Tag checkpoints `cp0-contracts`, `cp1-baselines`, `cp2-e2e`, `cp3-p1`, `cp4-demo-freeze`, and merge only when contract tests pass.

**Stack note:** `scipy` is a small addition to the preferred stack, needed for hierarchical clustering. `scikit-learn` is only needed if T1.7 is attempted.

## 12. Demo narrative and differentiators

The demo should prove three things in five minutes: the grouping is correct on data the system never trained on, the reduction does not hide real incidents, and every claim can be inspected. Fill every number from the measured experiment table; say "not measured" rather than quote an expectation.

**Five-minute flow**

1. **The problem (30 s).** One real day from the test split, in raw form: the alert firehose against the number of ground-truth incidents.
2. **The answer (45 s).** The same day as incident cards, with the notification count next to incident recall and swallow rate, never the reduction alone.
3. **One incident, opened (90 s).** Pick a mid-size test incident. Show the timeline, the dependency subgraph, and the origin ranking with its evidence and its caveat. Click one link to show the "why linked?" feature breakdown.
4. **Honesty moments (60 s).** Show a `tentative` cluster with its bridge alert and its nearest alternative cluster, an origin that abstains, and a small real incident that survives next to a large storm.
5. **The scoreboard (60 s).** Baselines B0–B3, our system, and the ablation table with confidence intervals, including components we dropped because they did not help. Close with time to surface from replay mode.

**Differentiators (each must be backed by something measured or inspectable)**

- Evaluated against explicit baselines and ablations, with incident-level bootstrap intervals and a documented leakage audit.
- Every grouping explained by stored feature values; no black box and no LLM.
- Preservation by design: no suppression, an *Unattached* lane, critical alerts always visible, and a visibility invariant of zero missing alerts.
- Origins as ranked hypotheses with abstention, benchmarked against no-skill baselines.
- Replay mode that measures how early an incident view becomes useful using only past alerts.
- Deterministic, laptop-runnable, one command to reproduce.

**Claims we will not make unless measured:** a percentage reduction, an accuracy figure, or "finds the root cause".

## 13. Open questions, decision and first five tasks

Every field name, parameter value and time estimate in this document is provisional until these are answered from the supplied files and the official rubric.

### Dataset schema

- [ ] What fields does each alert have: id, start time, end or resolve time, source, service, severity, rule or alert name, free text, tags?
- [ ] Timestamp format, time zone, granularity, and any known clock skew between sources?
- [ ] Is free text present, and did anonymization hash or remove tokens? (If hashed, fingerprints rely on token equality only.)
- [ ] How many days of data, how many incidents, and how many alerts per incident? This decides whether 60/20/20 splits and any learning are feasible.
- [ ] Are all alerts mapped to a service in the dependency map? How many are `UNKNOWN`?

### Ground truth

- [ ] Can an alert link to zero, one or several incidents? What share of alerts is unmatched?
- [ ] Is the incident link human-labelled or system-generated, and is it complete? Any known label noise?
- [ ] Is the incident's root cause recorded as a service id, a free-text note or a category? Is the recorded start time the first alert or the user-impact time?
- [ ] Do incident start and end times overlap each other often?

### Dependency map

- [ ] Directed or undirected, and does an edge mean "calls" or "depends on"? Weighted or typed?
- [ ] Static or versioned over the data period? Is it known to be incomplete?
- [ ] Degree distribution: which services are hubs?

### Rubric and logistics

- [ ] Scoring weights: accuracy versus explainability versus UI versus novelty? Which metrics do judges compute, and on which held-out data?
- [ ] Is there a hidden test set, and what prediction format is required?
- [ ] Are LLMs, external data or specific libraries allowed or penalized?
- [ ] Total time, submission format (repo, deck, live demo), and whether judges will run the code.
- [ ] What counts as a correct origin: exact service, top-k, or a category?

### Architecture decision

**Decision:** implement Architecture B: gated pair scoring over time, dependency, fingerprint and symptom features; average-linkage clustering with span cap, bridge detection and cohesion; ranked-hypothesis origin ranking with abstention; deterministic, read-only, no LLM. Architecture A is the baseline and the gate. Logistic-regression weights (C-lite) are tried only after B's ablations, and only if the data supports it. Every component must pass the keep/drop rule in 9.7.

### First five engineering tasks once the data and rubric are available

1. **Inspect and freeze.** Profile the dataset (counts by source, severity and service; time ranges; duplicates; alert-to-incident cardinality; incident durations and overlaps; dependency-graph degrees, hubs and cycles). Read the rubric. Write `DATA_REPORT.md`, freeze the contracts and write the purged chronological split manifest.
2. **Evaluation harness and floors.** Implement pairwise, BCubed, recovered/swallowed/fragmented, notification and visibility metrics, with hand-checked unit tests. Produce B0–B2 and the burst-purity ceiling D1 on validation.
3. **First end-to-end clustering.** Build bursts, gate, features and scoring with starting weights, then average-linkage clustering. Report D2 gate recall and the first validation numbers against B1/B2. Freeze `predictions.csv`.
4. **Origin ranker v0.** Implement `e_time`, `e_cover`, `e_cons` and abstention, plus the baselines O1–O4. Measure against the incident records and write evidence records.
5. **Serve a real run.** Stand up the FastAPI endpoints on a precomputed run and a minimal React incident list and detail view. Then start the tuning and ablation loop (E1–E7) while the UI matures.
