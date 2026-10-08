/* Workshop training: assessed jobs on the Golf Mk8 eHybrid.
 *
 * The method is the Strip Bay trainer's (platform/trainer/sim.js): a job is a
 * list of stages, a stage stays open until it is right and the next is locked
 * until then, and every wrong action is logged with the reason, so the end is
 * an assessor's record, not a score. Conditions are drawn at random each run
 * (pad and disc wear, which damper leaks, which plug is fouled), so a trainee
 * learns the method, not the answers.
 *
 * The difference here: the hands-on stages run on the workshop's own car, bolt
 * by bolt. The trainee picks the tool and sets the torque wrench; the workshop
 * reports every refusal (wrong tool, wrong order, wrong torque, a part outside
 * the job) and this module records it as a fault.
 *
 * Torque and angle figures come from the Golf Mk7 manual data the workshop
 * uses (jobs.js). Measured values on gauges are SIMULATION values and say so.
 */

const PROG = 'ehy-training-progress';
const loadProg = () => { try { return JSON.parse(localStorage.getItem(PROG) || '{}'); } catch (e) { return {}; } };
const saveProg = p => { try { localStorage.setItem(PROG, JSON.stringify(p)); } catch (e) { /* private window: progress is not kept */ } };
const rnd = a => a[Math.floor(Math.random() * a.length)];
const shuffle = a => { a = a.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
const wait = ms => new Promise(r => setTimeout(r, ms));
const f1 = v => v.toFixed(1), f2 = v => v.toFixed(2);
function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'on') for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn);
    else if (k === 'class') e.className = v; else e.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k.nodeType ? k : document.createTextNode(String(k)));
  return e;
}
const SIM = () => h('span', { class: 'simtag' }, 'simulation value');

export function createTraining(W) {
  const root = document.querySelector('#card-train');
  let run = null, stageApi = null;

  /* ── stage kinds ── */
  // hands-on stage on the 3D car: goals are checked after every action
  const doStage = ({ title, lead, cam, allow, goals, setup, tip }) => ({ kind: 'do', title, render(b, a) {
    if (setup) setup(a);
    W.showTray(true);
    if (cam) W.flyTo(...cam);
    a.allow = new Set(typeof allow === 'function' ? allow(a.st) : allow);
    if (lead) b.append(h('p', {}, lead));
    const list = h('ul', { class: 'goals' }); b.append(list);
    const gs = typeof goals === 'function' ? goals(a.st) : goals;
    const sel = h('div', { class: 'trsel' }); b.append(sel);
    b.append(h('p', { class: 'small' }, tip || 'Pick a tool in the tray, set the torque wrench where it is needed, then tap each bolt on the car. Tap a part to take it off or put it back.'));
    a.refresh = () => {
      list.textContent = '';
      let all = true;
      for (const g of gs) { const ok = !!g.ok(W, a.st); all &&= ok; list.append(h('li', { class: ok ? 'ok' : '' }, h('span', { class: 'tick' }, ok ? '✓' : ''), g.t)); }
      renderSel(sel, a);
      if (all && !a.done) a.pass(gs.at(-1).done || '');
    };
    a.refresh();
  } });
  // one question, one right answer
  const quiz = ({ title, lead, q, opts, cam, setup }) => ({ kind: 'quiz', title, setup, render(b, a) {
    if (cam) W.flyTo(...cam);
    if (lead) b.append(h('p', {}, typeof lead === 'function' ? lead(a.st) : lead));
    b.append(h('p', { class: 'q' }, q));
    const box = h('div', { class: 'opts' }); b.append(box);
    shuffle(typeof opts === 'function' ? opts(a.st) : opts).forEach(o => {
      const bt = h('button', { class: 'opt', type: 'button' }, o.t);
      bt.addEventListener('click', () => { if (a.done) return; if (o.ok) { bt.classList.add('ok'); a.pass(o.why); } else { bt.classList.add('no'); a.fail(o.why); } });
      box.append(bt);
    });
  } });
  // choose the next action; steps sharing `g` may go in any order; traps are plausible wrong actions
  const order = ({ title, lead, steps, traps = [], done: doneMsg, cam }) => ({ kind: 'order', title, render(b, a) {
    if (cam) W.flyTo(...cam);
    if (lead) b.append(h('p', {}, lead));
    const box = h('div', { class: 'opts' }), list = h('ol', { class: 'ticks' });
    b.append(h('p', { class: 'q' }, 'Choose the next action.'), box, list);
    const done = steps.map(() => false); let busy = false;
    const items = shuffle([...steps.map((s, i) => ({ s, i })), ...traps.map(t => ({ trap: t }))]);
    for (const it of items) {
      const bt = h('button', { class: 'opt', type: 'button' }, it.trap ? it.trap.t : it.s.t);
      bt.addEventListener('click', async () => {
        if (a.done) return; if (busy) return a.info('Wait for the current action to finish.');
        if (it.trap) { bt.remove(); return a.fail(it.trap.why); }
        const { s, i } = it;
        for (let j = 0; j < i; j++) if (!done[j] && !(s.g && steps[j].g === s.g)) return a.fail(s.early || 'Out of order. Something has to happen before this step.');
        busy = true; done[i] = true; bt.remove(); list.append(h('li', {}, s.t)); a.clear();
        if (s.note) a.info(s.note);
        if (s.anim) await s.anim(a);
        busy = false;
        if (done.every(Boolean)) a.pass(doneMsg);
      });
      box.append(bt);
    }
  } });
  // tap parts on the car: every target, nothing else
  const pickAll = ({ title, lead, targets, wrong, done: doneMsg, cam }) => ({ kind: 'pick', title, render(b, a) {
    if (cam) W.flyTo(...cam);
    W.focus(true);
    const want = new Set(targets(W, a.st)), got = new Set();
    b.append(h('p', {}, lead));
    const count = h('p', { class: 'q' }); b.append(count);
    const upd = () => { count.textContent = `${got.size} of ${want.size} found`; };
    upd();
    a.onPick = id => {
      if (a.done) return true;
      if (want.has(id)) { if (!got.has(id)) { got.add(id); W.flash(id); a.info(`${W.nameOf(id)}: yes.`); upd(); if (got.size === want.size) { W.focus(false); a.pass(doneMsg); } } return true; }
      a.fail(wrong(W, id)); return true;
    };
  } });

  /* ── the part you tapped, with what you can do to it ── */
  function renderSel(box, a) {
    box.textContent = '';
    const p = W.selectedPart(); if (!p) { box.append(h('p', { class: 'small' }, 'Tap a part on the car to work on it.')); return; }
    const row = h('div', { class: 'row2' });
    box.append(h('div', { class: 'trname' }, p.name, h('span', { class: 'pill' }, W.stateText(p))));
    if (p.fx) {
      const n = k => p.bolts.filter(b => b.userData.state === k).length, all = p.bolts.length;
      if (n('out') === all) row.append(h('button', { class: 'btn', type: 'button', on: { click: () => { W.fitBolts(p); a.refresh?.(); } } }, p.fx.renew ? 'Fit new bolts by hand' : 'Fit the bolts by hand'));
      else { const tn = W.toolName(); row.append(h('button', { class: 'btn', type: 'button', on: { click: () => { W.allBolts(p); a.refresh?.(); } } }, tn === 'Hands' ? 'Use your hands on all' : `Use the ${/^[A-Z]\d|^M\d/.test(tn) ? tn : tn.toLowerCase()} on all`)); }
      const data = h('button', { class: 'btn', type: 'button' }, 'Workshop data');
      data.addEventListener('click', () => { data.replaceWith(h('div', { class: 'spec' }, `${W.toolLabel(p.fx.tool)} · ${p.fx.nm != null ? p.fx.nm + ' Nm' : 'torque: erWin'}${p.fx.deg ? ' + ' + p.fx.deg + '°' : ''}${p.fx.renew ? ' · renew' : ''}`)); });
      row.append(data);
    } else if (p.removed) row.append(h('button', { class: 'btn', type: 'button', on: { click: () => { W.refitPart(p.id); a.refresh?.(); } } }, 'Put it back'));
    else if (!W.isFixed(p.id)) row.append(h('button', { class: 'btn', type: 'button', on: { click: () => { W.removePart(p.id); a.refresh?.(); } } }, 'Take it off'));
    if (p.hinge && !p.removed) row.append(h('button', { class: 'btn', type: 'button', on: { click: () => { W.toggleHinge(p.id); a.refresh?.(); } } }, W.isOpen(p) ? 'Close' : 'Open'));
    box.append(row);
  }

  /* ── shared checks ── */
  const off = id => w => w.byId[id]?.removed;
  const tight = id => w => { const p = w.byId[id]; return p && !p.removed && p.bolts.every(b => b.userData.state === 'in'); };
  const back = ids => w => ids.every(id => { const p = w.byId[id]; return p && !p.removed && (!p.bolts || p.bolts.every(b => b.userData.state === 'in')); });
  const outOfJob = (w, id) => `${w.nameOf(id)} is not part of this stage. Do what the stage asks, in order, and leave everything else alone.`;

  /* ───────── JOB: front brakes ───────── */
  const BRAKE_CAM = [[2.3, 0.95, 2.55], [0.72, 0.4, 1.28]];
  const brakes = {
    id: 'brakes', kind: 'Brakes · safety-critical', title: 'Front brakes, pads and discs',
    blurb: 'Customer: “Grinding from the front when braking.” Lift, measure, decide, renew, torque.',
    init() { const worn = Math.random() < 0.5; return { worn, pad: rnd([1.2, 1.4, 1.6, 1.8]), base: worn ? 27.6 + Math.random() * 0.25 : 28.6 + Math.random() * 0.5 }; },
    stages: [
      order({
        title: 'On the lift', cam: [[4.4, 1.6, 3.6], [0, 0.5, 0.3]],
        lead: 'Job card: “Grinding from the front when braking.” Golf 8 eHybrid. Get the car up safely.',
        steps: [
          { t: 'Slacken the front-left wheel bolts with the car on the ground' },
          { t: 'Lift arms under the four marked lifting points on the sills', early: 'Slacken the wheel bolts first, while the tyre holds the wheel still.' },
          { t: 'Raise it a little, shake-test it, then up to working height on the locks', anim: async () => { W.setLift(true); await wait(900); } },
        ],
        traps: [
          { t: 'Put a lift pad under the floor pan in the middle of the car', why: 'The eHybrid’s 13 kWh high-voltage battery sits under the floor there. Only the marked lifting points: a pad on the battery can crush it.' },
          { t: 'Undo the wheel bolts all the way with the car on the ground', why: 'Slacken only. A wheel with no bolts holding it can drop as the car rises.' },
        ],
        done: 'Car up on the locks, at the right points.',
      }),
      doStage({
        title: 'Front-left wheel off', cam: BRAKE_CAM,
        allow: ['fix_wheel_fl', 'wheel_fl'],
        goals: [{ t: 'Wheel bolts out', ok: off('fix_wheel_fl') }, { t: 'Wheel off and set aside', ok: off('wheel_fl'), done: 'Wheel off. The brake is in view.' }],
      }),
      {
        kind: 'measure', title: 'Measure before you decide',
        render(b, a) {
          const st = a.st; st.mic = []; st.used = {};
          W.flyTo([1.85, 0.72, 2.2], [0.76, 0.36, 1.28]);
          const minTh = 28.0;
          b.append(h('p', {}, 'Pads and disc thickness decide the job. The disc hat is stamped ', h('b', {}, `MIN TH ${f1(minTh)} mm`), ' (', SIM(), '). Pads: wear limit 2 mm not counting the backplate (manual).'));
          const val = h('div', { class: 'mval' }, '—'), cap = h('div', { class: 'mcap' }, 'Choose a measurement'), meter = h('div', { class: 'meter' }, val, cap);
          const set = (v, c) => { val.textContent = v; cap.textContent = c; };
          b.append(meter);
          const o = h('div', { class: 'opts two' }); b.append(o);
          o.append(h('button', { class: 'opt', type: 'button', on: { click: () => { st.used.pad = true; set(f1(st.pad) + ' mm', 'Pad gauge, inboard pad, thinnest point.'); } } }, 'Pad gauge, inboard pad'));
          o.append(h('button', { class: 'opt', type: 'button', on: { click: () => { st.used.vern = true; set(f1(st.base + 0.9) + ' mm', 'Vernier across the disc. It sits on the rusty lip at the outer edge.'); } } }, 'Vernier across the disc'));
          ['A', 'B', 'C'].forEach((p, i) => o.append(h('button', { class: 'opt', type: 'button', on: { click: () => { const v = st.base + (Math.random() - 0.5) * 0.12; st.mic[i] = v; set(f2(v) + ' mm', `Micrometer, point ${p}, on the swept face.`); } } }, `Micrometer, point ${p}`)));
          b.append(h('p', { class: 'q' }, 'What does this car need?'));
          const v = h('div', { class: 'opts' }); b.append(v);
          [['pads', 'New pads, the discs stay'], ['both', 'New pads and discs'], ['none', 'Nothing yet: the pads have life left']].forEach(([k, t]) => v.append(h('button', { class: 'opt', type: 'button', on: { click: e => {
            if (a.done) return;
            if (!st.used.pad) return a.fail('Measure the pads before deciding anything about them.');
            if (st.mic.filter(x => x != null).length < 3) return a.fail(st.used.vern ? 'The vernier reads the worn lip at the edge and gives a thicker disc than you have. Micrometer, three points on the swept face.' : 'Measure the disc with a micrometer at three points on the swept face first.');
            const right = st.worn ? 'both' : 'pads';
            if (k === right) { st.disc = k === 'both'; e.target.classList.add('ok'); return a.pass(st.worn ? 'Every reading is under MIN TH: pads and discs, and both sides of the axle on the real car.' : 'Pads are under the limit, the disc is over MIN TH: pads on both sides of the axle, discs stay.'); }
            e.target.classList.add('no');
            a.fail(k === 'none' ? `The pads are at ${f1(st.pad)} mm, under the 2 mm limit.` : st.worn ? `Every micrometer reading is under MIN TH ${f1(minTh)} mm. The discs have to go.` : 'The disc is over MIN TH at every point. A new one spends the customer’s money for nothing.');
          } } }, t)));
        },
      },
      doStage({
        title: 'Caliper off', cam: [[1.2, 0.85, 0.95], [0.72, 0.42, 1.2]],
        allow: ['bolts_caliper_fl', 'caliper_fl'],
        lead: 'The guide bolts are on the inboard side. Leave the brake hose connected.',
        goals: [{ t: 'Both caliper guide bolts out', ok: off('bolts_caliper_fl') }, { t: 'Caliper off the carrier', ok: off('caliper_fl'), done: 'Caliper off, hose still connected.' }],
      }),
      quiz({
        title: 'Where the caliper goes',
        q: 'The caliper is off and still on its hose. Where does it go while you work?',
        opts: [
          { t: 'Hung from the spring with a hook, hose slack', ok: true, why: 'The hose carries the pressure. Its weight on it damages the hose inside, where you cannot see it.' },
          { t: 'Left hanging on the brake hose', why: 'The hose is a pressure part. Hanging the caliper on it damages it inside.' },
          { t: 'Disconnected and on the bench', why: 'Opening the hydraulics means bleeding the brakes. Do not disconnect the hose to change pads (manual).' },
        ],
      }),
      {
        kind: 'branch', title: 'Pads out, and the disc if it goes',
        render(b, a) { const st = a.st;
          const allow = ['pads_fl', ...(st.disc ? ['bolts_carrier_fl', 'carrier_fl', 'screw_disc_fl', 'disc_fl'] : [])];
          const goals = [{ t: 'Old pads out', ok: off('pads_fl') }];
          if (st.disc) goals.push({ t: 'Carrier bolts out and carrier off', ok: off('carrier_fl') }, { t: 'Disc screw out and disc off', ok: off('disc_fl'), done: 'Pads, carrier and disc off. Clean the hub face before the new disc.' });
          else goals[0].done = 'Old pads out. The disc stays.';
          doStage({ title: '', allow, goals, cam: BRAKE_CAM }).render(b, a);
        },
      },
      quiz({
        title: 'Before the new parts go on',
        lead: st => st.disc ? 'The hub face under the old disc is rusty.' : 'New pads are thicker than the old ones, so the piston has to go back.',
        q: 'What do you do?',
        opts: st => st.disc ? [
          { t: 'Clean the hub face back to bare metal', ok: true, why: 'Rust on the hub face tilts the new disc and gives a pulsing pedal (run-out).' },
          { t: 'Grease the hub face so the disc comes off next time', why: 'Grease there is not a fix for rust and can reach the friction face. Clean, dry metal.' },
          { t: 'Leave it: the wheel bolts clamp the disc flat', why: 'They clamp it onto the rust. The disc runs out and the pedal pulses.' },
        ] : [
          { t: 'Check the fluid level, then push the piston straight back with a retraction tool', ok: true, why: 'Pushing the piston back sends fluid up to the reservoir. Check it will not overflow onto the paint.' },
          { t: 'Lever it back against the disc with a screwdriver', why: 'That scores the disc and can cock the piston in its bore.' },
          { t: 'Wind it back clockwise with a wind-back tool', why: 'This front piston pushes straight back. Wind-back tools are for screw-type rear pistons.' },
        ],
      }),
      {
        kind: 'branch', title: 'Refit to the data',
        render(b, a) { const st = a.st;
          const ids = ['fix_wheel_fl', 'wheel_fl', 'bolts_caliper_fl', 'caliper_fl', 'pads_fl', ...(st.disc ? ['bolts_carrier_fl', 'carrier_fl', 'screw_disc_fl', 'disc_fl'] : [])];
          const goals = [];
          if (st.disc) goals.push({ t: 'New disc on, retaining screw 4.5 Nm', ok: back(['disc_fl', 'screw_disc_fl']) }, { t: 'Carrier on, ribbed-collar bolts 200 Nm', ok: back(['carrier_fl', 'bolts_carrier_fl']) });
          goals.push({ t: 'New pads in', ok: back(['pads_fl']) }, { t: 'Caliper on, new guide bolts 35 Nm', ok: back(['caliper_fl', 'bolts_caliper_fl']) }, { t: 'Wheel on, bolts torqued', ok: back(['wheel_fl', 'fix_wheel_fl']), done: 'Everything back and torqued to the data.' });
          doStage({ title: '', allow: ids, goals, cam: BRAKE_CAM, tip: 'Look up each figure with Workshop data, set the torque wrench to it, then tap the bolts. Over or under the figure is not accepted.' }).render(b, a);
        },
      },
      {
        kind: 'star', title: 'Wheel bolts in a star',
        render(b, a) {
          let seq = [];
          b.append(h('p', {}, 'Tap the five bolts in the order you torque them.'));
          const pent = h('div', { class: 'pent' });
          const btns = [0, 1, 2, 3, 4].map(k => { const a0 = Math.PI / 2 - k / 5 * Math.PI * 2; const bt = h('button', { type: 'button', style: `left:${50 + Math.cos(a0) * 38}%;top:${50 - Math.sin(a0) * 38}%`, 'aria-label': 'Bolt ' + (k + 1) }); bt.addEventListener('click', () => hit(k)); pent.append(bt); return bt; });
          b.append(pent);
          const reset = () => { seq = []; btns.forEach(x => { x.textContent = ''; x.className = ''; }); };
          function hit(k) {
            if (a.done || seq.includes(k)) return;
            if (seq.length === 1) { const d = (k - seq[0] + 5) % 5; if (d === 1 || d === 4) { a.fail('That is the next bolt round. Cross the wheel: skip one each time.'); return reset(); } }
            if (seq.length >= 2) { const d1 = (seq[1] - seq[0] + 5) % 5, d = (k - seq.at(-1) + 5) % 5; if (d !== d1) { a.fail('Not a star. Going round the circle pulls the wheel off-square as it seats.'); return reset(); } }
            seq.push(k); btns[k].textContent = seq.length; btns[k].className = 'on';
            if (seq.length === 5) a.pass('Star order. Final torque with the car on the ground.');
          }
        },
      },
      quiz({
        title: 'Before it moves', cam: [[4.4, 1.6, 3.6], [0, 0.5, 0.3]], setup: () => W.setLift(false),
        lead: 'Both sides done, car back on the ground.',
        q: 'What happens before the car moves at all?',
        opts: [
          { t: 'Pump the pedal until it is firm, then check the fluid level', ok: true, why: 'The pistons are fully back: the first press only takes up the gap. The first stop would have no brakes.' },
          { t: 'Drive it round the block to bed the pads in', why: 'Not until the pedal is firm. The first press only moves the pistons out to the pads.' },
          { t: 'Hand it back: the job card is done', why: 'Pedal firm and fluid level first, then a road test.' },
        ],
      }),
    ],
  };

  /* ───────── JOB: front strut ───────── */
  const strut = {
    id: 'strut', kind: 'Suspension', title: 'Front strut, leaking damper',
    blurb: 'Customer: “Knocking over bumps, front end feels floaty.” Find it, take it out, refit to the data.',
    init() { return { side: rnd(['fl', 'fr']) }; },
    setup(st) { W.markLeak(st.side); },
    cleanup() { W.markLeak(null); },
    stages: [
      {
        kind: 'pick', title: 'Find the leaking damper',
        render(b, a) {
          const st = a.st; W.setLift(true); W.focus(true);
          const look = sx => W.flyTo([sx * 1.75, 0.72, 1.75], [sx * 0.63, 0.6, 1.3]);
          look(1);
          b.append(h('p', {}, 'Car up, wheels on (see-through for this stage). Walk round and look at both front dampers. A leaking one is wet with oil down the body, and dirt sticks to it.'),
            h('div', { class: 'row2' }, h('button', { class: 'btn', type: 'button', on: { click: () => look(1) } }, 'Look at the left strut'), h('button', { class: 'btn', type: 'button', on: { click: () => look(-1) } }, 'Look at the right strut')),
            h('p', { class: 'q' }, 'Tap the damper that is leaking.'));
          a.onPick = id => {
            if (a.done) return true;
            const m = /^strut_(fl|fr)$/.exec(id); if (!m) { a.fail('Look at the struts: the damper bodies behind each front wheel.'); return true; }
            if (m[1] === st.side) { W.focus(false); a.pass(`Yes: oil down the ${st.side === 'fl' ? 'left' : 'right'} damper body. A dry, dusty one is normal.`); }
            else a.fail('That one is dry. Look for the damper wet with oil and caked with dirt.');
            return true;
          };
        },
      },
      quiz({
        title: 'What to renew',
        q: 'One damper is leaking. What goes on the order?',
        opts: [
          { t: 'Both front dampers, as a pair', ok: true, why: 'Dampers are renewed in pairs across an axle so both sides damp the same. This sim does the leaking side; on the car, both.' },
          { t: 'Just the leaking one', why: 'One new and one worn damper on the same axle damp differently: the car pulls and wallows. Pairs.' },
          { t: 'The leaking damper and its coil spring', why: 'The spring is not the fault. Dampers in pairs; springs only if broken or sagged.' },
        ],
      }),
      {
        kind: 'branch', title: 'Strut out',
        render(b, a) { const k = a.st.side, K = id => id + '_' + k;
          W.setLift(true);
          doStage({ title: '', cam: [[k === 'fl' ? 1.9 : -1.9, 1.05, 2.4], [k === 'fl' ? 0.66 : -0.66, 0.62, 1.3]],
            allow: [K('fix_wheel'), K('wheel'), K('bolt_hosebracket'), K('nuts_droplink'), K('bolt_strutclamp'), K('bolts_topmount'), K('strut')],
            lead: 'The top mount bolts are reached from the engine bay with the bonnet open.',
            goals: [{ t: 'Wheel off', ok: off(K('wheel')) }, { t: 'Brake hose bracket off the strut', ok: off(K('bolt_hosebracket')) }, { t: 'Coupling rod nuts off', ok: off(K('nuts_droplink')) },
              { t: 'Pinch bolt out of the bearing housing', ok: off(K('bolt_strutclamp')) }, { t: 'Top mount bolts out', ok: off(K('bolts_topmount')) }, { t: 'Strut out', ok: off(K('strut')), done: 'Strut out, bearing housing still on its swivel joint and track rod.' }] }).render(b, a);
        },
      },
      quiz({
        title: 'On the bench',
        q: 'The new damper needs the old spring and top mount. Before the piston rod nut comes off:',
        opts: [
          { t: 'Compress the spring evenly with a proper strut spring compressor', ok: true, why: 'The spring is held compressed by that nut. Undone with the spring loaded, the top mount leaves at speed.' },
          { t: 'Undo the nut with an impact gun so the rod does not spin', why: 'The spring is still loaded behind that nut. Compress it first, every time.' },
          { t: 'Cut the coil spring to release the load', why: 'A cut loaded spring releases its energy unpredictably. Compressor, then the nut. The nut is renewed: 60 Nm (manual).' },
        ],
      }),
      quiz({
        title: 'The pinch bolt',
        q: 'The pinch bolt goes back into the bearing housing. Which way round?',
        opts: [
          { t: 'Tip of the bolt pointing in the direction of travel, new bolt and nut', ok: true, why: 'The manual says the tip points in the direction of travel, and the bolt is renewed: 70 Nm + 180°.' },
          { t: 'Either way: it is a through bolt', why: 'The manual specifies the direction: tip pointing in the direction of travel.' },
          { t: 'Head toward the front, old bolt cleaned', why: 'Tip toward the direction of travel, and the bolt and nut are renewed (manual).' },
        ],
      }),
      {
        kind: 'branch', title: 'Strut in, to the data',
        render(b, a) { const k = a.st.side, K = id => id + '_' + k;
          doStage({ title: '', cam: [[k === 'fl' ? 1.9 : -1.9, 1.05, 2.4], [k === 'fl' ? 0.66 : -0.66, 0.62, 1.3]],
            allow: [K('fix_wheel'), K('wheel'), K('bolt_hosebracket'), K('nuts_droplink'), K('bolt_strutclamp'), K('bolts_topmount'), K('strut')],
            tip: 'Look up each figure with Workshop data. Several are torque plus a further angle: torque wrench first, then the angle gauge.',
            goals: [{ t: 'Strut in, top mount bolts 15 Nm + 90°', ok: back([K('strut'), K('bolts_topmount')]) }, { t: 'Pinch bolt 70 Nm + 180°', ok: back([K('bolt_strutclamp')]) },
              { t: 'Coupling rod nuts 65 Nm', ok: back([K('nuts_droplink')]) }, { t: 'Hose bracket 8 Nm', ok: back([K('bolt_hosebracket')]) }, { t: 'Wheel on and torqued', ok: back([K('wheel'), K('fix_wheel')]), done: 'Strut in, every fastener to the data.' }] }).render(b, a);
        },
      },
      quiz({
        title: 'Before it goes back',
        q: 'The strut is in and everything is torqued. What else does this job need?',
        opts: [
          { t: 'A wheel alignment check', ok: true, why: 'A new strut can move camber and toe. Check the alignment before the car goes back.' },
          { t: 'Nothing: the pinch bolt locates the strut exactly', why: 'Tolerances stack up. Check the alignment.' },
          { t: 'Re-torque everything after 50 miles', why: 'The stretch bolts are already torque-plus-angle. What it needs is an alignment check.' },
        ],
      }),
    ],
  };

  /* ───────── JOB: spark plugs ───────── */
  const plugs = {
    id: 'plugs', kind: 'Engine · hybrid', title: 'Spark plugs, 1.4 eHybrid',
    blurb: 'Service item, with a hybrid’s own trap: an engine that can start by itself.',
    init() { return { cyl: rnd([1, 2, 3, 4]), kind: rnd(['oil', 'carbon']) }; },
    stages: [
      order({
        title: 'Make it safe to work on', cam: [[1.9, 1.9, 3.3], [-0.05, 0.6, 1.5]],
        lead: 'On a plug-in hybrid the petrol engine is started by the system, not the key: to warm the cabin, top up the battery or answer a hard press of the pedal.',
        steps: [
          { t: 'Switch off: READY light out', g: 'off' },
          { t: 'Key out of range of the car, so it cannot be switched back on', g: 'off' },
          { t: 'Charging cable unplugged', g: 'off' },
          { t: 'Bonnet open and propped' },
        ],
        traps: [
          { t: 'Leave it in READY with the engine off so the fan keeps running', why: 'In READY the system can start the engine at any moment, with your hands near the belt and fan.' },
          { t: 'Leave it on charge while you work', why: 'With the cable in, the system is live and can run pumps and fans. Unplug it.' },
        ],
        done: 'Off, key away, cable out. The engine cannot start itself.',
      }),
      doStage({
        title: 'Plugs out', cam: [[1.1, 1.55, 2.35], [-0.03, 0.78, 1.55]],
        allow: ['dgea_airbox', 'dgea_coils', 'spark_plugs'],
        lead: 'The air box sits on top of the DGEA. Coils come straight up after unplugging.',
        goals: [{ t: 'Air box off', ok: off('dgea_airbox') }, { t: 'Coils out', ok: off('dgea_coils') }, { t: 'Plugs out with the spark plug socket', ok: off('spark_plugs'), done: 'Four plugs out, laid out in cylinder order.' }],
      }),
      quiz({
        title: 'Read the plugs',
        lead: st => `Laid out in order: ${[1, 2, 3, 4].map(c => `cylinder ${c}: ${c === st.cyl ? (st.kind === 'oil' ? 'black and wet with oil' : 'dry, sooty black') : 'light grey-tan'}`).join('; ')}. (Plug condition is a simulation value.)`,
        q: 'What do you do?',
        opts: st => st.kind === 'oil' ? [
          { t: `New plugs, and report oil getting into cylinder ${st.cyl} for investigation`, ok: true, why: 'A wet oily plug means oil is reaching that cylinder: valve stem seals or rings. A plug hides it, it does not fix it.' },
          { t: 'New plugs and hand it back', why: `Cylinder ${st.cyl} is wet with oil. Plugs are the service item; the oil is a fault to report.` },
          { t: `Clean plug ${st.cyl} and refit the old set`, why: 'Plugs at the service interval are renewed, and the oil is still a fault to report.' },
        ] : [
          { t: `New plugs, and report cylinder ${st.cyl} running rich for diagnosis`, ok: true, why: 'Dry black soot on one plug means that cylinder runs rich: an injector is the first suspect. Report it.' },
          { t: 'New plugs: sooty plugs are normal on a hybrid', why: `Only cylinder ${st.cyl} is sooty. One rich cylinder is a fault, whatever the drivetrain.` },
          { t: 'Swap plug ' + st.cyl + ' to another cylinder to see if it follows', why: 'That is a misfire test, and these plugs are being renewed anyway. Report the rich cylinder.' },
        ],
      }),
      quiz({
        title: 'New plugs in',
        q: 'Starting a new plug in the aluminium head:',
        opts: [
          { t: 'Start it by hand on the extension, then torque to the data', ok: true, why: 'By hand you feel a crossed thread before it cuts. Then 22 Nm (manual).' },
          { t: 'Run it in with a ratchet to save time', why: 'A ratchet drives a crossed plug straight through the aluminium thread. Start it by hand.' },
          { t: 'Copper grease on the electrode end so it comes out next time', why: 'Never on the electrode end. Follow the plug maker: these go in clean and dry.' },
        ],
      }),
      doStage({
        title: 'Back together, to the data', cam: [[1.1, 1.55, 2.35], [-0.03, 0.78, 1.55]],
        allow: ['dgea_airbox', 'dgea_coils', 'spark_plugs'],
        tip: 'Fit the plugs by hand, run them in with the spark plug socket, then the torque wrench at the figure in Workshop data.',
        goals: [{ t: 'Plugs in, 22 Nm', ok: back(['spark_plugs']) }, { t: 'Coils in', ok: back(['dgea_coils']) }, { t: 'Air box on', ok: back(['dgea_airbox']), done: 'Plugs to the data, coils and air box back on.' }],
      }),
    ],
  };

  /* ───────── JOB: high voltage ───────── */
  const hv = {
    id: 'hv', kind: 'High voltage · awareness', title: 'Know the high-voltage parts',
    blurb: 'Find every high-voltage part on the car, and what to do when one is damaged. Awareness only: HV work is for qualified technicians.',
    init() { return {}; },
    stages: [
      pickAll({
        title: 'Find every high-voltage part', cam: [[3.2, 2.6, 4.0], [0, 0.5, 0.4]],
        lead: 'High-voltage parts and cables are orange. The body is see-through for this stage. Tap each one on the car.',
        targets: w => w.parts.filter(p => p.tags.includes('hv') && !p.tags.includes('fastener') && !p.tags.includes('seal')).map(p => p.id),
        wrong: (w, id) => `${w.nameOf(id)} is not high voltage. Look for orange parts and cables.`,
        done: 'Every high-voltage part found.',
      }),
      quiz({
        title: 'Damaged orange cable',
        q: 'Under the car you see an orange cable with its conduit split and the insulation scuffed. What now?',
        opts: [
          { t: 'Hands off. Stop work on the car, mark it, and report it to an HV-qualified technician', ok: true, why: 'Damaged HV insulation is a shock hazard. Only a qualified technician makes the system safe and decides what happens next.' },
          { t: 'Wrap it in insulating tape and carry on', why: 'Tape is not a repair for HV insulation, and you are not qualified to judge it. Stop and report.' },
          { t: 'Pull the 12 V battery and carry on', why: 'The 12 V battery is not the high-voltage system. The HV battery stays charged. Stop and report.' },
        ],
      }),
      order({
        title: 'Before HV work (qualified technicians)',
        lead: 'Who does what, in order, before anyone works on a high-voltage part. This is awareness: the procedure itself is VW’s, for the exact car.',
        steps: [
          { t: 'Confirm the technician is HV-qualified for this vehicle' },
          { t: 'Follow VW’s procedure to switch off and isolate the HV system' },
          { t: 'Secure it against being switched back on: lock and tag' },
          { t: 'Prove it dead, by the qualified technician, with a tester rated for the job' },
        ],
        traps: [
          { t: 'Cut an orange cable to be sure it is dead', why: 'Never. Isolation follows the manufacturer’s procedure; cutting a live cable is how people are killed.' },
          { t: 'Check the HV battery with an ordinary multimeter', why: 'Only a tester rated for the voltage and category, used by a qualified technician, following the procedure.' },
        ],
        done: 'The right order, and the right people.',
      }),
    ],
  };

  const JOBS = [brakes, strut, plugs, hv];

  /* ───────── running a job ───────── */
  function list() {
    run = null; stageApi = null; W.trainingActive(false);
    root.textContent = '';
    const prog = loadProg();
    root.append(h('h2', {}, 'Training'), h('p', {}, 'Assessed jobs on this car. Each stage stays locked until it is right, and every wrong action is logged with the reason, like an assessor’s record.'));
    const tiles = h('div', { class: 'tiles' });
    for (const j of JOBS) {
      const p = prog[j.id];
      tiles.append(h('button', { class: 'tile', type: 'button', on: { click: () => open(j.id) } },
        h('span', { class: 'eyebrow' }, j.kind), h('b', {}, j.title), h('span', { class: 'blurb' }, j.blurb),
        h('span', { class: 'meta2' }, `${j.stages.length} stages`, p?.done ? h('span', { class: 'pill ok' }, p.best ? `Done · best ${p.best} fault${p.best > 1 ? 's' : ''}` : 'Done · clean') : null)));
    }
    tiles.append(h('button', { class: 'tile', type: 'button', on: { click: () => W.openDemo() } },
      h('span', { class: 'eyebrow' }, 'Demonstration · not assessed'), h('b', {}, 'Engine out, strip and refit'), h('span', { class: 'blurb' }, 'Watch the engine, hybrid module and gearbox come out step by step, then strip the engine on the stand.')));
    root.append(tiles);
  }
  function open(id) {
    const job = JOBS.find(j => j.id === id); if (!job) return list();
    run?.job.cleanup?.(); W.resetCar();
    run = { job, idx: 0, faults: 0, log: [], t0: Date.now(), st: job.init() };
    job.setup?.(run.st);
    W.trainingActive(true);
    stage();
  }
  const faultText = () => run.faults ? `${run.faults} not accepted` : 'No faults';
  function stage() {
    root.textContent = '';
    const s = run.job.stages[run.idx];
    const head = h('div', { class: 'trhead' }, h('button', { class: 'btn link', type: 'button', on: { click: () => { run?.job.cleanup?.(); W.resetCar(); list(); } } }, '‹ All jobs'), h('span', { class: 'pill ' + (run.faults ? 'off' : 'ok'), id: 'tr-fc' }, faultText()));
    const dots = h('ol', { class: 'stepper', 'aria-label': 'Stages' }, run.job.stages.map((x, i) => h('li', { class: i < run.idx ? 'done' : i === run.idx ? 'now' : '', title: x.title }, i < run.idx ? '✓' : String(i + 1))));
    const body = h('div', { class: 'trbody' }), fb = h('div', { class: 'fb', role: 'status', 'aria-live': 'polite' }), foot = h('div', { class: 'row2' });
    root.append(head, h('div', { class: 'stepn' }, `${run.job.title} · stage ${run.idx + 1} of ${run.job.stages.length}`), dots, h('h2', {}, s.title), body, fb, foot);
    const a = stageApi = {
      st: run.st, done: false, onPick: null, refresh: null,
      say(kind, title, msg) { fb.className = 'fb ' + kind; fb.textContent = ''; fb.append(h('b', {}, title), msg ? ' ' + msg : ''); },
      info(msg) { a.say('info', '', msg); },
      clear() { fb.className = 'fb'; fb.textContent = ''; },
      fail(msg) { run.faults++; run.log.push({ stage: s.title, msg }); a.say('bad', 'Not accepted.', msg); const fc = document.querySelector('#tr-fc'); if (fc) { fc.textContent = faultText(); fc.className = 'pill off'; } },
      pass(msg) {
        if (a.done) return; a.done = true; a.say('ok', 'Accepted.', msg || '');
        const last = run.idx === run.job.stages.length - 1;
        foot.append(h('button', { class: 'btn pri', type: 'button', on: { click: () => { run.idx++; last ? report() : stage(); } } }, last ? 'Finish and sign off' : 'Next stage'));
      },
    };
    W.showTray(false);
    s.setup?.(a);
    s.render(body, a);
  }
  function report() {
    const secs = Math.round((Date.now() - run.t0) / 1000);
    const prog = loadProg(), prev = prog[run.job.id];
    prog[run.job.id] = { done: true, best: prev?.done ? Math.min(prev.best, run.faults) : run.faults, runs: (prev?.runs || 0) + 1 };
    saveProg(prog);
    stageApi = null; W.trainingActive(false); run.job.cleanup?.();
    root.textContent = '';
    root.append(h('div', { class: 'stepn' }, `${run.job.title} · ${Math.floor(secs / 60)} min ${secs % 60} s`),
      h('h2', {}, run.faults ? 'Signed off, with faults recorded' : 'Signed off. Clean run.'),
      h('p', {}, run.faults ? `${run.faults} action${run.faults > 1 ? 's were' : ' was'} not accepted. Each is something that would cost time, a part or an injury on a real car.` : 'Every stage right first time.'));
    if (run.log.length) root.append(h('ol', { class: 'log' }, run.log.map(l => h('li', {}, h('b', {}, (l.stage || 'Job') + ': '), l.msg))));
    const id = run.job.id;
    root.append(h('div', { class: 'row2' }, h('button', { class: 'btn pri', type: 'button', on: { click: () => open(id) } }, 'Run again, new conditions'), h('button', { class: 'btn', type: 'button', on: { click: () => { W.resetCar(); list(); } } }, 'All jobs')));
  }

  return {
    list, open,
    get active() { return !!(run && stageApi && !stageApi.doneJob); },
    // the workshop calls these
    allowed(p) { if (!stageApi || !run) return ''; const al = stageApi.allow; if (!al) return 'Finish this stage first: it is not a hands-on stage.'; return al.has(p.id) ? '' : outOfJob(W, p.id); },
    fault(msg) { if (stageApi && !stageApi.done) stageApi.fail(msg); },
    changed() { stageApi?.refresh?.(); },
    pick(id) { return stageApi?.onPick ? stageApi.onPick(id) : false; },
    get run() { return run; },
  };
}
