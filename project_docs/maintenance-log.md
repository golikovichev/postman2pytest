\## Maintenance Task 1 - Corrective Maintenance



\### Problem

When different requests in the same Postman collection used different

authentication headers, postman2pytest combined them into one shared

auth\_headers fixture.



As a result, every authenticated request received all authentication

headers from the collection.



Example:

\- Request A used Authorization: Bearer ...

\- Request B used X-Api-Key: ...



Both generated tests received both authentication headers.



\### Reproduction

A new regression test was added:



test\_different\_auth\_schemes\_are\_not\_mixed\_between\_requests



The test initially failed and showed that the shared auth\_headers fixture

was applied completely to both requests.



\### Root Cause

The generator only stored whether a request had authentication:



has\_auth\_per\_request



It did not store which authentication headers belonged to each request.



The Jinja template therefore generated:



\*\*auth\_headers



for every authenticated request.



\### Solution

The generator was changed to keep track of authentication header names

for each individual request using:



auth\_names\_per\_request



The template was then changed so that each request selects only the

authentication headers it actually requires.



Example generated code:



Bearer request:



"Authorization": auth\_headers\["Authorization"]



API key request:



"X-Api-Key": auth\_headers\["X-Api-Key"]



\### Files Changed

\- core/generator.py

\- templates/test\_collection.jinja2

\- tests/test\_auth\_fixtures.py

\- tests/test\_generator.py



\### Testing

Original baseline:

209 tests passed.



A new regression test was added, bringing the total to 210 tests.



Final result:

210 tests passed.



\### Maintenance Type

Corrective maintenance.



The change corrects incorrect behavior in the generated pytest tests

when multiple authentication schemes are used in the same collection.



\### Status

Completed.





\--------------------------------------------------------------------------------

\## Maintenance Task 2 - Additive Maintenance



\### Feature

Added limited support for Postman pre-request scripts.



The supported pattern is:



pm.environment.set("key", "value");



This allows simple literal environment-variable assignments in a Postman

pre-request script to be carried over into the generated pytest code.



\### Previous Behavior

Before this change, pre-request events were not used as request setup

functionality.



The parser handled Postman `test` events for expected status codes and

assertions, but did not expose pre-request environment assignments.



\### Reproduction / Feature Test

A new parser test was added:



test\_parse\_prerequest\_environment\_set



Before implementation, the test failed because ParsedRequest had no

`prerequest\\\_variables` field.



\### Implementation

The parser was extended to detect literal pre-request assignments such as:



pm.environment.set("token", "abc123");



These assignments are stored in:



prerequest\_variables



The pytest template was then extended to generate equivalent Python code

before the HTTP request, for example:



os.environ\["token"] = "abc123"



\### Files Changed

\- core/parser.py

\- templates/test\_collection.jinja2

\- tests/test\_parser.py

\- tests/test\_generator.py

\- project\_docs/maintenance-log.md



\### Testing

Added:

\- parser test for extracting pre-request variables

\- generator test for emitting the environment assignment



Previous full suite:

210 tests passed.



Expected new full suite:

212 tests.



\### Maintenance Type

Additive maintenance.



This change adds a new supported Postman feature that was not previously

available in the generated pytest output.



\### Scope

The implementation currently supports only simple literal string assignments

using:



pm.environment.set("key", "value");



More complex JavaScript expressions are not supported.



\### Status

Completed.



Final regression result:

212 tests passed.



\--------------------------------------------------------------------------------------



\## Maintenance Task 3 - Preventive Maintenance



\### Problem

Generated multipart upload tests opened files with `open(..., "rb")`

without explicit context management.



\### Risk

File handles could remain open longer than necessary and potentially

cause resource-management problems.



\### Verification

A new test was added:



test\_generated\_file\_upload\_uses\_context\_manager



The test initially failed because the generated code did not use a

`with open(...)` context manager.



\### Solution

The generator and Jinja template were changed so multipart upload files

are opened inside a context manager and are automatically closed after

the request completes.



\### Testing

The focused preventive test passed.

All body-mode tests passed.

Final full regression result: 213 tests passed.



\### Maintenance Type

Preventive maintenance.



\### Status

Completed.

