-- Demo data so the engine + RAG have something to run against before you ingest
-- your real licensed definitions. Illustrative values only — NOT verified coding.

-- A BMW G-series (CAN-FD) platform + body module
insert into platform (id, make, family, year_from, bus, can_bitrate, canfd_data_bitrate)
values ('00000000-0000-0000-0000-0000000000b1', 'BMW', 'G-series', 2019, 'canfd', 500000, 2000000)
on conflict do nothing;

insert into ecu (id, platform_id, key, name, req_id, resp_id, safety_critical)
values ('00000000-0000-0000-0000-0000000000e1',
        '00000000-0000-0000-0000-0000000000b1',
        'FEM_BODY', 'Front Electronic Module (body)', 1777, 1650, false)
on conflict do nothing;

-- A comfort feature (illustrative offsets)
insert into coding_definition
  (ecu_id, feature_key, label, description, kind, did, byte_offset, bit_offset,
   bit_length, options, legal_class, risk, source, verified)
values
  ('00000000-0000-0000-0000-0000000000e1',
   'mirror_fold_on_lock', 'Fold mirrors on lock',
   'Automatically folds the door mirrors when the car is locked.',
   'fdl', 12288, 7, 0, 1,
   '[{"label":"On","raw":1},{"label":"Off","raw":0}]',
   'comfort', 'low', 'reverse_engineered', false)
on conflict do nothing;

-- A VAG (classic CAN) platform + central electrics, with a lighting feature
insert into platform (id, make, family, year_from, bus)
values ('00000000-0000-0000-0000-0000000000b2', 'VAG', 'MQB', 2016, 'can')
on conflict do nothing;

insert into ecu (id, platform_id, key, name, req_id, resp_id)
values ('00000000-0000-0000-0000-0000000000e2',
        '00000000-0000-0000-0000-0000000000b2',
        '09_CENTRAL_ELECTRICS', 'Central Electrics (BCM)', 1809, 1713)
on conflict do nothing;

insert into coding_definition
  (ecu_id, feature_key, label, description, kind, did, byte_offset, bit_offset,
   bit_length, options, legal_class, risk, source, verified)
values
  ('00000000-0000-0000-0000-0000000000e2',
   'comfort_windows_remote', 'Close windows with remote',
   'Hold the lock button on the key to close all windows.',
   'long_coding', 1536, 12, 4, 1,
   '[{"label":"On","raw":1},{"label":"Off","raw":0}]',
   'comfort', 'low', 'vcds_label', false)
on conflict do nothing;

-- A couple of DTCs
insert into dtc_library (code, make, title, plain_english, severity, typical_cause,
                         typical_fix, est_cost_low, est_cost_high)
values
  ('P2002', null, 'DPF efficiency below threshold',
   'The diesel particulate filter is clogging and not clearing itself, usually from short trips.',
   'medium', 'Repeated short/low-speed journeys preventing regeneration',
   'A 20-min motorway drive to force a regen; if it persists, a forced regen or clean.',
   180, 320),
  ('P0401', null, 'EGR flow insufficient',
   'Exhaust gas recirculation is not flowing enough — often a sooted-up EGR valve.',
   'medium', 'Carbon build-up in the EGR valve/passages',
   'Clean or replace the EGR valve.', 120, 400)
on conflict do nothing;

-- ---------------------------------------------------------------------------
-- Toyota (UDS over CAN) — a customer-setting coding example
-- ---------------------------------------------------------------------------
insert into platform (id, make, family, year_from, bus, protocol)
values ('00000000-0000-0000-0000-0000000000b3', 'Toyota', 'CAN', 2012, 'can', 'uds')
on conflict do nothing;
insert into ecu (id, platform_id, key, name, req_id, resp_id)
values ('00000000-0000-0000-0000-0000000000e3',
        '00000000-0000-0000-0000-0000000000b3', 'BODY_MAIN', 'Main Body ECU', 1937, 1841)
on conflict do nothing;
insert into coding_definition
  (ecu_id, feature_key, label, description, kind, did, byte_offset, bit_offset,
   bit_length, options, legal_class, risk, operation, source, verified)
values
  ('00000000-0000-0000-0000-0000000000e3', 'auto_door_lock_speed',
   'Auto-lock doors when moving', 'Locks the doors automatically once you drive off.',
   'long_coding', 1552, 3, 1, 1,
   '[{"label":"On","raw":1},{"label":"Off","raw":0}]',
   'comfort', 'low', 'coding', 'community', false)
on conflict do nothing;

-- ---------------------------------------------------------------------------
-- French — PSA (DiagBox-class, UDS over CAN). Renault mirrors this shape.
-- ---------------------------------------------------------------------------
insert into platform (id, make, family, year_from, bus, protocol)
values ('00000000-0000-0000-0000-0000000000b4', 'PSA', 'CAN', 2014, 'can', 'uds')
on conflict do nothing;
insert into ecu (id, platform_id, key, name, req_id, resp_id)
values ('00000000-0000-0000-0000-0000000000e4',
        '00000000-0000-0000-0000-0000000000b4', 'BSI_BODY', 'BSI (body control)', 1808, 1712)
on conflict do nothing;
insert into coding_definition
  (ecu_id, feature_key, label, description, kind, did, byte_offset, bit_offset,
   bit_length, options, legal_class, risk, operation, source, verified)
values
  ('00000000-0000-0000-0000-0000000000e4', 'follow_me_home_lights',
   'Follow-me-home lights', 'Headlights stay on to light your way after locking.',
   'long_coding', 1600, 2, 0, 1,
   '[{"label":"On","raw":1},{"label":"Off","raw":0}]',
   'lighting', 'low', 'coding', 'community', false)
on conflict do nothing;

-- ---------------------------------------------------------------------------
-- HIGH-RISK REPAIR examples (RoutineControl). Legitimate repairs, hard-gated:
-- risk='high', require allow_high_risk + licensed security. NOT consumer features.
-- ---------------------------------------------------------------------------
insert into coding_definition
  (ecu_id, feature_key, label, description, kind, routine_id,
   options, legal_class, risk, operation, security_level, source, verified)
values
  ('00000000-0000-0000-0000-0000000000e1', 'abs_pump_bleed',
   'ABS hydraulic bleed / new-pump init',
   'Cycles the ABS pump to bleed air after replacing the modulator. Workshop-only.',
   'routine', 20481, '[]', 'safety', 'high', 'abs_service', 3, 'reverse_engineered', false),
  ('00000000-0000-0000-0000-0000000000e1', 'esl_init',
   'Steering-column lock (ESL/ELV) initialisation',
   'Pairs a replaced electronic steering lock to the car. Workshop-only.',
   'routine', 20482, '[]', 'safety', 'high', 'esl_service', 3, 'reverse_engineered', false)
on conflict do nothing;
