
# WS-C Email/Dialer Reliability — Validation Receipt

Generated: 2026-08-31T04:36:56.293485Z
Overall PASS: True

## Email Transport (orbit/n8n/workflows/email-transport.json)
- Schedule: Every 15 min (interval minutes 15) preserved
- API gates: claim -> SMTP -> report ok/false preserved
- Duplicate Authorization fixed: True
- Every POST retryOnFail:true maxTries:3 wait 5000-10000: True
- Send Email error branch report_fail ok:false: True
- claim onError:continueRegularOutput: True
- Structural valid: True

## Dialer Dispatch (orbit/n8n/workflows/dialer-dispatch.json)
- Schedule: Weekdays 8 AM triggerAtHour 8 preserved
- Single Authorization Bearer ORBIT_SERVICE_TOKEN: True
- POST retry 3/5000: True
- Idempotency / salted date key: True
- onError continueRegularOutput preserved: True
- Structural valid: True

## Backend Idempotency
- orbit/backend/app/routers/dialer.py: SessionIn.idempotency_key optional, create_session checks existing name+date and returns existing to prevent duplicate Morning session

## Evidence Files
- .gauntlet/evidence/ws-c-validation-receipt.json
- .gauntlet/evidence/ws-c-email-transport-receipt.json
- .gauntlet/evidence/ws-c-dialer-dispatch-receipt.json
- .gauntlet/evidence/ws-c-n8n__workflows__email-transport.json.diff
- .gauntlet/evidence/ws-c-n8n__workflows__dialer-dispatch.json.diff
- .gauntlet/evidence/ws-c-backend__app__routers__dialer.py.diff

## Diff Summary
### email-transport.json
- Fixed Authorization header to single `=Bearer {{$env.ORBIT_SERVICE_TOKEN}}` for tick, due, claim, report_ok, report_fail
- Added retryOnFail:true maxTries:3 waitBetweenTries:5000 to tick, claim, report_ok, report_fail (SMTP already had 3/10000)
- Moved claim onError from parameters to node level continueRegularOutput
- Preserved scheduleTrigger 15min, executionOrder v1, claim->SMTP->report connections

### dialer-dispatch.json
- Fixed Authorization to `=Bearer {{$env.ORBIT_SERVICE_TOKEN}}`
- Added retryOnFail 3/5000 to session and operator handoff POSTs
- Added Idempotency-Key header `=dialer-{{$now.format('yyyy-MM-dd')}}` and body idempotency_key `'dialer:' + $now.format('yyyy-MM-dd')` to Build P1/P2 session
- Backend: dialer.py deduplicates by name+date when idempotency_key or Morning session name

