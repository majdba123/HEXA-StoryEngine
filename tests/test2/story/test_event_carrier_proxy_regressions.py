from __future__ import annotations
from pathlib import Path
import pytest
from app.canonical import CanonicalAsset, CanonicalPackage, CanonicalScene, CanonicalScriptSpan, CanonicalSemanticEvent, CanonicalVisualLocator
from app.models import StoryBeat, Transcript, TranscriptWord, VisualAsset
from app.story.activation import SemanticActivationPlanner
from app.story.identity import VisualIdentityBinder

def visual(asset_id: str, bbox: tuple[int, int, int, int], *, role='object', independent=True) -> VisualAsset:
    return VisualAsset(id=asset_id, scene_id='SCENE_001', role=role, image_path=Path(f'{asset_id}.png'), extraction_method='test2-event-carrier', source_bbox=bbox, source_canvas_width=1000, source_canvas_height=1000, source_area_ratio=bbox[2] * bbox[3] / 1000000, can_animate_independently=independent, confidence=1.0)

def semantic(asset_id='intent', locator=(0.5, 0.5, 0.4, 0.4), *, text='alpha', start=0, end=5) -> CanonicalAsset:
    return CanonicalAsset(unit_id=asset_id, asset_id=asset_id, scene_id='SCENE_001', script_text=text, script_span=CanonicalScriptSpan(text=text, global_char_start=start, global_char_end=end), visual_locator=CanonicalVisualLocator(cx=locator[0], cy=locator[1], width=locator[2], height=locator[3]) if locator else None, confidence=1.0)

def event(event_id: str, target: str, text: str, start: int, end: int, order: int, depends=()) -> CanonicalSemanticEvent:
    return CanonicalSemanticEvent(semantic_event_id=event_id, scene_id='SCENE_001', script_text=text, script_span=CanonicalScriptSpan(text=text, global_char_start=start, global_char_end=end), sequence_order=order, visual_leader_asset_id=target, participant_asset_ids=(target,), depends_on_event_ids=tuple(depends))

def package(assets, events, script: str) -> CanonicalPackage:
    scene = CanonicalScene(id='SCENE_001', image_path=Path('scene.png'), order=0, script_char_start=0, script_char_end=len(script), units=tuple(assets), semantic_events=tuple(events))
    return CanonicalPackage(root=Path('.'), package_id='event-carrier-regression', script=script, scenes=(scene,), has_authoritative_semantics=True)

def transcript(script: str) -> Transcript:
    words = []
    cursor = 0
    t = 0.1
    for token in script.split():
        start = script.index(token, cursor)
        end = start + len(token)
        words.append(TranscriptWord(start=t, end=t + 0.2, text=token, char_start=start, char_end=end))
        cursor = end
        t += 0.3
    return Transcript(duration=t + 0.2, segments=[], words=words, timing_source='forced_alignment')

def beat(script: str, tr: Transcript) -> StoryBeat:
    return StoryBeat(id='beat-001', scene_id='SCENE_001', start=0.0, end=tr.duration, audio_start=0.0, audio_end=tr.duration, narration=script, primary_asset_ids=[], support_asset_ids=[], action='INTRODUCE')

def proxies(pkg: CanonicalPackage, tr: Transcript, assets: list[VisualAsset], *, existing=(), windows=()):
    return SemanticActivationPlanner()._reused_semantic_event_proxies(package=pkg, transcript=tr, scene=pkg.scenes[0], beat=beat(pkg.script or '', tr), assets=assets, windows=list(windows), existing_proxies=list(existing))

@pytest.mark.parametrize('bbox', [(300, 300, 160, 160), (540, 300, 160, 160), (300, 540, 160, 160), (540, 540, 160, 160), (320, 340, 180, 140), (500, 520, 180, 140)])
def test_unique_approximate_locator_carrier(bbox):
    sem = semantic()
    runtime = visual('runtime', bbox)
    other = visual('other', (800, 800, 100, 100))
    binder = VisualIdentityBinder()
    strict = binder.bind(scene=package((sem,), (), 'alpha').scenes[0], semantic_assets=[sem], assets=[runtime, other])
    assert 'intent' not in strict.matches and 'intent' in strict.unresolved_locator_ids
    carrier = binder.region_carrier(semantic_asset=sem, assets=[runtime, other])
    assert carrier and carrier.real_asset_id == 'runtime'

@pytest.mark.parametrize('left,right', [((300, 350, 180, 180), (520, 350, 180, 180)), ((330, 330, 170, 170), (500, 500, 170, 170)), ((300, 420, 190, 160), (510, 420, 190, 160)), ((390, 300, 160, 190), (390, 510, 160, 190))])
def test_region_carrier_near_tie_abstains(left, right):
    assert VisualIdentityBinder().region_carrier(semantic_asset=semantic(), assets=[visual('left', left), visual('right', right)]) is None

@pytest.mark.parametrize('asset', [visual('tiny', (300, 300, 80, 80)), visual('background', (300, 300, 180, 180), role='background'), visual('decorative', (300, 300, 180, 180), role='decorative'), visual('locked', (300, 300, 180, 180), independent=False)])
def test_region_carrier_rejects_insufficient_or_ineligible(asset):
    assert VisualIdentityBinder().region_carrier(semantic_asset=semantic(), assets=[asset]) is None

def test_region_carrier_requires_locator():
    assert VisualIdentityBinder().region_carrier(semantic_asset=semantic(locator=None), assets=[visual('runtime', (300, 300, 180, 180))]) is None

def test_proxy_preserves_event_without_promoting_identity():
    script = 'alpha beta'
    sem = semantic()
    ev = event('E1', 'intent', 'alpha', 0, 5, 1)
    pkg = package((sem,), (ev,), script)
    rt = visual('runtime', (300, 300, 160, 160))
    tr = transcript(script)
    strict = VisualIdentityBinder().bind(scene=pkg.scenes[0], semantic_assets=[sem], assets=[rt])
    assert strict.matches == {}
    rows = proxies(pkg, tr, [rt])
    assert len(rows) == 1 and rows[0].authority == 'FINAL_PACKAGE_REGION_CARRIER_PROXY' and (rows[0].semantic_unit_id == 'intent')

def test_three_events_share_one_region_carrier():
    script = 'alpha beta gamma'
    sem = semantic()
    evs = (event('E1', 'intent', 'alpha', 0, 5, 1), event('E2', 'intent', 'beta', 6, 10, 2, ('E1',)), event('E3', 'intent', 'gamma', 11, 16, 3, ('E2',)))
    pkg = package((sem,), evs, script)
    rows = proxies(pkg, transcript(script), [visual('runtime', (300, 300, 160, 160))])
    assert [r.semantic_event_id for r in rows] == ['E1', 'E2', 'E3'] and {r.asset_id for r in rows} == {'runtime'}

def test_dependency_reuses_single_proven_carrier():
    script = 'alpha beta'
    source = semantic('source', text='alpha')
    target = semantic('target', None, text='beta', start=6, end=10)
    evs = (event('E1', 'source', 'alpha', 0, 5, 1), event('E2', 'target', 'beta', 6, 10, 2, ('E1',)))
    pkg = package((source, target), evs, script)
    rows = proxies(pkg, transcript(script), [visual('runtime', (300, 300, 160, 160))])
    assert [r.semantic_event_id for r in rows] == ['E1', 'E2'] and rows[1].authority == 'FINAL_PACKAGE_DEPENDENCY_CARRIER_PROXY'

def test_dependency_multiple_carriers_abstain():
    script = 'alpha beta gamma'
    left = semantic('left', (0.3, 0.5, 0.3, 0.4), text='alpha')
    right = semantic('right', (0.7, 0.5, 0.3, 0.4), text='beta', start=6, end=10)
    target = semantic('target', None, text='gamma', start=11, end=16)
    evs = (event('E1', 'left', 'alpha', 0, 5, 1), event('E2', 'right', 'beta', 6, 10, 2), event('E3', 'target', 'gamma', 11, 16, 3, ('E1', 'E2')))
    pkg = package((left, right, target), evs, script)
    rows = proxies(pkg, transcript(script), [visual('left-runtime', (150, 300, 140, 180)), visual('right-runtime', (710, 300, 140, 180))])
    assert {r.semantic_event_id for r in rows} == {'E1', 'E2'}

def test_existing_event_representation_is_not_duplicated():
    from app.story.windows import StoryAssetActivation
    script = 'alpha'
    sem = semantic()
    ev = event('E1', 'intent', 'alpha', 0, 5, 1)
    pkg = package((sem,), (ev,), script)
    tr = transcript(script)
    rt = visual('runtime', (300, 300, 160, 160))
    trusted = StoryAssetActivation(asset_id='runtime', semantic_unit_id='intent', trigger_text='alpha', trigger_char_start=0, trigger_char_end=5, spoken_start=0.1, spoken_end=0.3, confidence=1.0, source='unified_final_package', policy='EXPLICIT', activation_policy='OWN_WINDOW', phrase_start=0.1, phrase_end=0.3, reveal_start=0.1, semantic_peak=0.2, settle_at=0.3, semantic_event_id='E1')
    assert proxies(pkg, tr, [rt], windows=[trusted]) == []

@pytest.mark.parametrize('bbox,expected', [((431, 431, 138, 138), False), ((430, 430, 140, 140), True), ((400, 400, 180, 180), True), ((350, 350, 240, 240), True), ((300, 300, 400, 400), True)])
def test_realistic_coverage_boundary(bbox, expected):
    assert (VisualIdentityBinder().region_carrier(semantic_asset=semantic(), assets=[visual('runtime', bbox)]) is not None) is expected

@pytest.mark.parametrize('top,runner,expected', [((400, 400, 200, 200), (410, 410, 180, 180), False), ((400, 400, 200, 200), (411, 411, 178, 178), True), ((380, 380, 220, 220), (400, 400, 180, 180), True), ((380, 380, 220, 220), (390, 390, 210, 210), False), ((350, 350, 250, 250), (420, 420, 140, 140), True)])
def test_realistic_margin_boundary(top, runner, expected):
    carrier = VisualIdentityBinder().region_carrier(semantic_asset=semantic(), assets=[visual('top', top), visual('runner', runner)])
    assert (carrier is not None) is expected
    if carrier:
        assert carrier.real_asset_id == 'top'

@pytest.mark.parametrize('count', [1, 2, 3, 5])
def test_candidate_cardinality(count):
    assets = [visual('winner', (350, 350, 240, 240))]
    distractors = [(305, 305, 120, 120), (575, 305, 105, 105), (305, 575, 95, 95), (585, 585, 80, 80)]
    assets += [visual(f'd{i}', b) for i, b in enumerate(distractors[:count - 1], 1)]
    carrier = VisualIdentityBinder().region_carrier(semantic_asset=semantic(), assets=assets)
    assert carrier and carrier.real_asset_id == 'winner'

@pytest.mark.parametrize('locator,bbox', [((0.18, 0.18, 0.24, 0.24), (80, 80, 160, 160)), ((0.82, 0.18, 0.24, 0.24), (700, 80, 160, 160)), ((0.18, 0.82, 0.24, 0.24), (80, 700, 160, 160)), ((0.82, 0.82, 0.24, 0.24), (700, 700, 160, 160)), ((0.5, 0.5, 0.6, 0.2), (330, 430, 340, 140)), ((0.5, 0.5, 0.2, 0.6), (430, 330, 140, 340))])
def test_varied_locator_shapes(locator, bbox):
    carrier = VisualIdentityBinder().region_carrier(semantic_asset=semantic(locator=locator), assets=[visual('runtime', bbox), visual('far', (850, 450, 70, 70))])
    assert carrier and carrier.real_asset_id == 'runtime'

def test_exact_coverage_tie_abstains_independent_of_order():
    sem = semantic()
    a = visual('zzz', (330, 400, 180, 180))
    b = visual('aaa', (490, 400, 180, 180))
    binder = VisualIdentityBinder()
    assert binder.region_carrier(semantic_asset=sem, assets=[a, b]) is None and binder.region_carrier(semantic_asset=sem, assets=[b, a]) is None

def test_many_out_of_region_distractors_do_not_change_winner():
    assets = [visual('winner', (360, 360, 220, 220))] + [visual(f'far-{i}', (20 + i * 70, 20, 50, 50)) for i in range(10)]
    carrier = VisualIdentityBinder().region_carrier(semantic_asset=semantic(), assets=assets)
    assert carrier and carrier.real_asset_id == 'winner'

def test_pass2_like_child_can_be_unique_best_carrier():
    carrier = VisualIdentityBinder().region_carrier(semantic_asset=semantic(), assets=[visual('parent', (370, 370, 150, 150)), visual('parent:secondary-01', (330, 330, 230, 230))])
    assert carrier and carrier.real_asset_id == 'parent:secondary-01'

def test_parent_and_pass2_child_near_tie_abstains():
    assert VisualIdentityBinder().region_carrier(semantic_asset=semantic(), assets=[visual('parent', (350, 350, 200, 200)), visual('parent:secondary-01', (450, 450, 200, 200))]) is None

def test_five_event_reused_carrier_chain():
    script = 'alpha beta gamma delta omega'
    spans = [('alpha', 0, 5), ('beta', 6, 10), ('gamma', 11, 16), ('delta', 17, 22), ('omega', 23, 28)]
    sem = semantic()
    evs = tuple((event(f'E{i}', 'intent', txt, s, e, i, (f'E{i - 1}',) if i > 1 else ()) for i, (txt, s, e) in enumerate(spans, 1)))
    rows = proxies(package((sem,), evs, script), transcript(script), [visual('runtime', (360, 360, 160, 160))])
    assert [r.semantic_event_id for r in rows] == ['E1', 'E2', 'E3', 'E4', 'E5']

def test_dependency_fanout_reuses_one_carrier():
    script = 'alpha beta gamma'
    source = semantic('source', text='alpha')
    b = semantic('b', None, text='beta', start=6, end=10)
    c = semantic('c', None, text='gamma', start=11, end=16)
    evs = (event('E1', 'source', 'alpha', 0, 5, 1), event('E2', 'b', 'beta', 6, 10, 2, ('E1',)), event('E3', 'c', 'gamma', 11, 16, 3, ('E1',)))
    rows = proxies(package((source, b, c), evs, script), transcript(script), [visual('runtime', (360, 360, 160, 160))])
    assert [r.semantic_event_id for r in rows] == ['E1', 'E2', 'E3'] and {r.asset_id for r in rows} == {'runtime'}

def test_multiple_dependencies_same_carrier_remain_unambiguous():
    script = 'alpha beta gamma'
    source = semantic('source', text='alpha')
    middle = semantic('middle', None, text='beta', start=6, end=10)
    target = semantic('target', None, text='gamma', start=11, end=16)
    evs = (event('E1', 'source', 'alpha', 0, 5, 1), event('E2', 'middle', 'beta', 6, 10, 2, ('E1',)), event('E3', 'target', 'gamma', 11, 16, 3, ('E1', 'E2')))
    rows = proxies(package((source, middle, target), evs, script), transcript(script), [visual('runtime', (360, 360, 160, 160))])
    assert rows[-1].authority == 'FINAL_PACKAGE_DEPENDENCY_CARRIER_PROXY' and rows[-1].asset_id == 'runtime'

def test_own_region_carrier_wins_over_dependency_fallback():
    script = 'alpha beta'
    source = semantic('source', (0.25, 0.5, 0.3, 0.4), text='alpha')
    target = semantic('target', (0.75, 0.5, 0.3, 0.4), text='beta', start=6, end=10)
    evs = (event('E1', 'source', 'alpha', 0, 5, 1), event('E2', 'target', 'beta', 6, 10, 2, ('E1',)))
    rows = proxies(package((source, target), evs, script), transcript(script), [visual('source-runtime', (150, 360, 150, 160)), visual('target-runtime', (700, 360, 150, 160))])
    by = {r.semantic_event_id: r for r in rows}
    assert by['E2'].asset_id == 'target-runtime' and by['E2'].authority == 'FINAL_PACKAGE_REGION_CARRIER_PROXY'

@pytest.mark.parametrize('canvas,bbox', [((1920, 1080), (720, 370, 300, 220)), ((1080, 1920), (390, 690, 220, 340)), ((3840, 2160), (1480, 760, 560, 420)), ((720, 1280), (250, 450, 160, 250)), ((640, 360), (240, 125, 110, 80))])
def test_region_carrier_normalizes_non_square_canvases(canvas, bbox):
    width, height = canvas
    runtime = VisualAsset(id='runtime', scene_id='SCENE_001', role='object', image_path=Path('runtime.png'), extraction_method='test2-event-carrier', source_bbox=bbox, source_canvas_width=width, source_canvas_height=height, source_area_ratio=bbox[2] * bbox[3] / (width * height), can_animate_independently=True, confidence=1.0)
    carrier = VisualIdentityBinder().region_carrier(semantic_asset=semantic(), assets=[runtime])
    assert carrier is not None
    assert carrier.real_asset_id == 'runtime'

@pytest.mark.parametrize('distractor_count', [5, 10, 20, 40])
def test_region_carrier_remains_stable_with_many_out_of_region_assets(distractor_count):
    assets = [visual('winner', (360, 360, 220, 220))]
    for index in range(distractor_count):
        x = 5 + index % 10 * 60
        y = 5 + index // 10 * 45
        assets.append(visual(f'far-{index}', (x, y, 35, 35)))
    carrier = VisualIdentityBinder().region_carrier(semantic_asset=semantic(), assets=list(reversed(assets)))
    assert carrier is not None
    assert carrier.real_asset_id == 'winner'

@pytest.mark.parametrize('role,independent', [('background', True), ('decorative', True), ('object', False)])
def test_ineligible_full_overlap_never_beats_valid_region_carrier(role, independent):
    invalid = visual('invalid', (300, 300, 400, 400), role=role, independent=independent)
    valid = visual('valid', (360, 360, 220, 220))
    carrier = VisualIdentityBinder().region_carrier(semantic_asset=semantic(), assets=[invalid, valid])
    assert carrier is not None
    assert carrier.real_asset_id == 'valid'

@pytest.mark.parametrize('order', [('winner', 'a', 'b', 'c'), ('c', 'winner', 'b', 'a'), ('b', 'a', 'c', 'winner'), ('a', 'c', 'winner', 'b')])
def test_region_carrier_selection_is_input_order_independent(order):
    rows = {'winner': visual('winner', (350, 350, 240, 240)), 'a': visual('a', (40, 40, 80, 80)), 'b': visual('b', (780, 40, 80, 80)), 'c': visual('c', (40, 780, 80, 80))}
    carrier = VisualIdentityBinder().region_carrier(semantic_asset=semantic(), assets=[rows[name] for name in order])
    assert carrier is not None
    assert carrier.real_asset_id == 'winner'

@pytest.mark.parametrize('event_count', [6, 8, 10, 12])
def test_long_event_chain_preserves_every_event_on_one_proven_carrier(event_count):
    tokens = [f'word{index}' for index in range(1, event_count + 1)]
    script = ' '.join(tokens)
    spans = []
    cursor = 0
    for token in tokens:
        spans.append((token, cursor, cursor + len(token)))
        cursor += len(token) + 1
    sem = semantic(text=script, start=0, end=len(script))
    evs = tuple((event(f'E{index}', 'intent', token, start, end, index, (f'E{index - 1}',) if index > 1 else ()) for index, (token, start, end) in enumerate(spans, start=1)))
    rows = proxies(package((sem,), evs, script), transcript(script), [visual('runtime', (360, 360, 160, 160))])
    assert [row.semantic_event_id for row in rows] == [f'E{index}' for index in range(1, event_count + 1)]
    assert {row.asset_id for row in rows} == {'runtime'}

def test_dependency_diamond_reuses_only_the_single_proven_carrier():
    script = 'alpha beta gamma delta'
    source = semantic('source', text='alpha')
    left = semantic('left', None, text='beta', start=6, end=10)
    right = semantic('right', None, text='gamma', start=11, end=16)
    result = semantic('result', None, text='delta', start=17, end=22)
    evs = (event('E1', 'source', 'alpha', 0, 5, 1), event('E2', 'left', 'beta', 6, 10, 2, ('E1',)), event('E3', 'right', 'gamma', 11, 16, 3, ('E1',)), event('E4', 'result', 'delta', 17, 22, 4, ('E2', 'E3')))
    rows = proxies(package((source, left, right, result), evs, script), transcript(script), [visual('runtime', (360, 360, 160, 160))])
    assert [row.semantic_event_id for row in rows] == ['E1', 'E2', 'E3', 'E4']
    assert rows[-1].authority == 'FINAL_PACKAGE_DEPENDENCY_CARRIER_PROXY'
    assert {row.asset_id for row in rows} == {'runtime'}

def test_region_proxy_confidence_never_exceeds_semantic_or_runtime_evidence():
    script = 'alpha'
    sem = CanonicalAsset(unit_id='intent', asset_id='intent', scene_id='SCENE_001', script_text='alpha', script_span=CanonicalScriptSpan(text='alpha', global_char_start=0, global_char_end=5), visual_locator=CanonicalVisualLocator(cx=0.5, cy=0.5, width=0.4, height=0.4), confidence=0.72)
    ev = event('E1', 'intent', 'alpha', 0, 5, 1)
    runtime = visual('runtime', (300, 300, 160, 160))
    runtime.confidence = 0.61
    rows = proxies(package((sem,), (ev,), script), transcript(script), [runtime])
    assert len(rows) == 1
    assert rows[0].confidence <= 0.61 + 1e-09
