# exordos_tests

## Scheduled element tests

`scheduled_element_tests` runs the combinations listed in
[element-tests.json](element-tests.json). Each entry specifies an
element, whether to test an update, the backend (`realm` or `bootstrap`), and a
cron expression in UTC. Existing reusable workflows perform the tests.
Bootstrap entries can also set `free-disk-space: true` to free runner disk space
before testing, as required by `world`.

To add a combination, add an entry to that list. If its schedule is new, also add
the cron expression to `on.schedule` in
[scheduled_element_tests.yml](.github/workflows/scheduled_element_tests.yml).
GitHub requires schedule triggers to be declared in the workflow itself. Add new
elements to the manual `element` choices there as well.

For a manual run, select an element and mode (`install`, `update`, or `all`).
Only configured combinations run; selecting `all` for both runs the entire list.
A combination absent from the list fails selection with an explanatory error.
Matrix tests run independently, so one failure does not cancel the others.

Run the selection checks with:

```sh
python3 -m unittest discover -s .github/tests -v
```
