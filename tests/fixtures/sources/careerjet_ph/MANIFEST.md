# careerjet_ph fixtures

- `careerjet_ph_20260916_01.json` — fetched 2026-09-16 (~01:10 +08:00) via the
  CareerJet publisher API (`locale_code=en_PH`, keywords=`remote`,
  location=`Philippines`, pagesize=50). Response `type=JOBS`, `hits=8280`,
  50 jobs on page 1. First job: "Remote Accountant (CPA)" @ "remote raven".
- Auth: API key as HTTP Basic username; publisher account must whitelist the
  caller egress IP (was `110.54.230.176` at fetch time) and the request must
  send a `Referer` header matching the domain declared in the publisher
  account (`GIGGREGATOR_CAREERJET_REFERER`, defaults to the production site).
- Edge cases present: HTML markup inside titles/descriptions (stripped by the
  adapter), structured salary fields (`salary_min`/`salary_max`/`salary_type`)
  re-serialized to raw pay strings, empty-salary listings, `date` in mixed
  formats.
