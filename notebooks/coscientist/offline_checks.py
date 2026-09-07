"""Offline checks for the coscientist module: no LLM calls, no network."""
import sys, random
sys.path.insert(0, '/mnt/berstorage/RCP/rcp-platform/notebooks')
from coscientist.state import EloTable, Memory, ResearchPlan, Hypothesis, TaskQueue, simulate_elo
from coscientist import ranking as rank, proximity as prox, supervisor as sup, reflection as ref

PLAN = ResearchPlan(goal="g", preferences=["p"], constraints=["c"])
ok = lambda m: print("  ok:", m)

print("== Elo update rule (Methods: initial 1200; classical K=32) ==")
t = EloTable(); t.add("a"); t.add("b")
assert t.initial == 1200.0 and t.k == 32.0 and t.rating("a") == 1200.0
assert abs(t.expected("a", "b") - 0.5) < 1e-12
d, dl = t.update("a", "b")
assert (d, dl) == (16.0, -16.0) and t.ratings == {"a": 1216.0, "b": 1184.0}
ok("equal ratings -> +/-K/2 = 16; ratings 1216/1184")
t2 = EloTable(); t2.ratings = {"s": 1600.0, "w": 1200.0}; t2.games = {"s": 0, "w": 0}
assert abs(t2.expected("s", "w") - 10/11) < 1e-3
before = sum(t2.ratings.values()); up, _ = t2.update("w", "s")
assert abs(sum(t2.ratings.values()) - before) < 1e-9 and abs(up - 32*(1-1/11)) < 1e-6
ok("400-pt gap -> E=0.909; upset pays +29.1; update is zero-sum")
t3 = EloTable(); t3.ratings = {"s": 1600.0, "w": 1200.0}; t3.games = {"s": 0, "w": 0}
assert t3.update("s", "w")[0] < 3.0
ok("expected win pays little (+%.2f)" % t3.update("s", "w")[0])
t4 = EloTable(); assert t4.add("x") is True and t4.add("x") is False
ok("AddToTournament is idempotent (Supp. Note 8)")
tab = simulate_elo({"A": 2.0, "B": 1.0, "C": 0.0, "D": -1.5}, 400, seed=1)
assert [h for h, _ in tab.top(4)] == list("ABCD")
ok("Bradley-Terry ordering recovered after 400 synthetic matches: %s" % {h: round(r) for h, r in tab.top(4)})

print("== Tournament pairing ==")
m = Memory("/tmp/cs_check", PLAN)
for i, (rnd, elo, games) in enumerate([(0, 1200, 5), (0, 1400, 5), (2, 1200, 0), (0, 1200, 5)]):
    h = Hypothesis(f"H{i}", f"t{i}", "", "", "", "", "", round=rnd)
    m.hypotheses[h.hid] = h; m.elo.ratings[h.hid] = float(elo); m.elo.games[h.hid] = games
m.proximity = {("H0", "H3"): 0.95}
sc = {(a, b): s for s, a, b in rank.pair_scores(m, list(m.hypotheses.values()), current_round=2)}
assert sc[("H0", "H3")] > sc[("H0", "H1")], sc      # similarity dominates
ok("similar pair (0.95) outranks a dissimilar pair of the same age/rating")
assert sc[("H2", "H3")] > sc[("H0", "H1")]          # H2 is new and never played
ok("newer + never-played pair outranks an old, fully-played pair")
m2 = Memory("/tmp/cs_check1b", PLAN)                # isolate the top-rank term: same age, same games
for i, elo in enumerate([1200, 1200, 1400]):
    h = Hypothesis(f"K{i}", f"t{i}", "", "", "", "", "", round=0)
    m2.hypotheses[h.hid] = h; m2.elo.ratings[h.hid] = float(elo); m2.elo.games[h.hid] = 2
sc2 = {(a, b): s for s, a, b in rank.pair_scores(m2, list(m2.hypotheses.values()), current_round=0)}
assert sc2[("K0", "K2")] > sc2[("K0", "K1")] and sc2[("K1", "K2")] > sc2[("K0", "K1")]
ok("with age/similarity/match-count held equal, pairs containing the top-rated idea rank higher")
picked = rank.choose_pairs(m, list(m.hypotheses.values()), 3, 2, random.Random(0), max_per_hyp=1)
seen = [x for p in picked for x in p]
assert len(seen) == len(set(seen)), picked
ok("max_per_hyp=1 -> no hypothesis appears twice in a round: %s" % picked)
bal = rank.balanced_pairs(m, list(m.hypotheses.values()), random.Random(0))
assert "H2" in bal[0][1:], bal[0]
ok("balanced pairing (joint tournament) starts with the least-played hypothesis")

print("== Task queue + weighting ==")
q = TaskQueue()
q.push("ranking", "RunTournamentBatch", priority=5)
q.push("reflection", "ReviewHypothesis", "H01", priority=1)
q.push("reflection", "ReviewHypothesis", "H02", priority=1)
assert [t.label() for t in (q.pop(), q.pop(), q.pop())] == \
       ["reflection.ReviewHypothesis(H01)", "reflection.ReviewHypothesis(H02)", "ranking.RunTournamentBatch"]
assert q.pop() is None
ok("priority order with FIFO tie-break; empty queue returns None")
cfg = sup.SupervisorConfig(max_ideas=12, target_matches_per_idea=3.0, metareview_period=2)
w0 = sup.agent_weights(sup.SystemStatistics(round=0), cfg)
w_backlog = sup.agent_weights(sup.SystemStatistics(round=1, n_hypotheses=4, n_active=4, n_unreviewed=4), cfg)
w_climb = sup.agent_weights(sup.SystemStatistics(round=5, n_hypotheses=8, n_active=8, n_in_tournament=8,
                                                 matches_per_idea=3.4, top_elo_gain=25), cfg)
w_stall = sup.agent_weights(sup.SystemStatistics(round=6, n_hypotheses=8, n_active=8, n_in_tournament=8,
                                                 matches_per_idea=3.4, top_elo_gain=1, evo_win_rate=0.6), cfg)
w_full = sup.agent_weights(sup.SystemStatistics(round=9, n_hypotheses=12, n_active=12, n_in_tournament=12,
                                                matches_per_idea=3.5, top_elo_gain=1), cfg)
assert w_backlog["reflection"] > w0["reflection"] and w_backlog["reflection"] > w_backlog["evolution"]
ok("review backlog -> reflection dominates")
assert w0["ranking"] > w0["evolution"] and w0["generation"] > w0["metareview"]
ok("cold start -> generation/ranking, not evolution or meta-review")
assert w_stall["evolution"] > w_climb["evolution"] * 5
ok("Elo stalls -> evolution switches on (%.2f vs %.2f while climbing)" % (w_stall["evolution"], w_climb["evolution"]))
assert w_full["generation"] < w0["generation"] / 3
ok("population at MaxIdeas -> generation decays (%.2f vs %.2f)" % (w_full["generation"], w0["generation"]))
assert sup.agent_weights(sup.SystemStatistics(round=3, n_active=3, rounds_since_metareview=2), cfg)["metareview"] > 1
ok("meta-review fires on its period")

print("== Proximity clustering / de-duplication (hand-built graph) ==")
tiny = Memory("/tmp/cs_check2", PLAN)
for n in "xyz": tiny.hypotheses[n] = Hypothesis(n, n, "", "", "", "", "")
tiny.proximity = {("x", "y"): 0.9, ("y", "z"): 0.7, ("x", "z"): 0.1}
assert prox.clusters(tiny, list("xyz"), 0.95) == [["x"], ["y"], ["z"]]
assert prox.clusters(tiny, list("xyz"), 0.8) == [["x", "y"], ["z"]]
assert prox.clusters(tiny, list("xyz"), 0.6) == [["x", "y", "z"]]
ok("single-linkage thresholds 0.95 / 0.8 / 0.6 -> singletons / {x,y}+{z} / chained")
assert tiny.sim("y", "x") == 0.9 and tiny.sim("x", "q") == 0.0
ok("similarity lookup is symmetric; unknown pair -> 0.0")
assert [p[:2] for p in prox.duplicates(tiny, list("xyz"), 0.85)] == [("x", "y")]
tiny.elo.ratings = {"x": 1180.0, "y": 1220.0, "z": 1200.0}; tiny.elo.games = {k: 1 for k in "xyz"}
dropped = prox.dedupe(tiny, 0.85)
assert dropped == [("x", "y", 0.9)] and tiny.get("x").status == "duplicate"
assert [h.hid for h in tiny.active()] == ["y", "z"]
ok("de-duplication drops the lower-Elo twin (%s) and it leaves the tournament" % dropped)

print("== Reflection quick filter ==")
assert ref.passes({"correctness": 8, "quality": 9, "novelty": 7, "safety": 8})[0]
assert not ref.passes({"correctness": 3, "quality": 7, "novelty": 6, "safety": 9})[0]
assert not ref.passes({"correctness": 7, "quality": 6, "novelty": 2, "safety": 8})[0]
assert not ref.passes({"correctness": 7, "quality": 6, "novelty": 6, "safety": 4})[0]
assert ref.passes({"correctness": 4, "quality": 4, "novelty": 3, "safety": 5})[0]   # exactly on the bar
ok("thresholds correctness>=4, quality>=4, novelty>=3, safety>=5, boundary inclusive")

print("== Ranking verdict parsing ==")
assert rank.parse_verdict('... better hypothesis: 2') == 2
assert rank.parse_verdict('**better idea: 1**') == 1
assert rank.parse_verdict('better idea: 1 ... better idea: 2') == 2      # last verdict wins
assert rank.parse_verdict('no verdict here') is None
ok("verdict regex handles both paper phrasings, markdown bold, and no-verdict")

print("\nALL OFFLINE CHECKS PASSED")
