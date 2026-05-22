.PHONY: install lint test test-countries test-weather test-cross-env test-ci report report-generate clean clean-allure clean-skills

install:
	pip install -r requirements.txt

lint:
	flake8 . --count --max-line-length=100
	mypy src utils conftest.py --ignore-missing-imports

test:
	pytest --alluredir=allure-results -v

test-countries:
	pytest --env countries --alluredir=allure-results -v

test-weather:
	pytest --env weather --alluredir=allure-results -v

test-cross-env:
	pytest --env cross-env --alluredir=allure-results -v

# Local convenience (CI: clean-allure → weather → countries → cross-env in ci.yml)
test-ci: clean-allure
	pytest --env weather --alluredir=allure-results -v
	pytest --env countries --alluredir=allure-results -v
	pytest --env cross-env --alluredir=allure-results -v

report:
	npx allure-commandline serve allure-results

# Static HTML report (upload allure-report/ from CI or open index.html locally)
report-generate:
	npx --yes allure-commandline generate allure-results -o allure-report --clean

clean-allure:
	rm -rf allure-results allure-report

# Remove timestamped skill outputs only (not tests/, src/, seeds, or received_sources/)
clean-skills:
	@echo "Cleaning skill generated outputs under .claude/skills/ ..."
	@for dir in \
	  .claude/skills/testcase-generator/generated_spec_sheets \
	  .claude/skills/test-data-generator/generated_test_data \
	  .claude/skills/test-generator/generated_pytest_modules \
	  .claude/skills/test-generator/received_test_data \
	  .claude/skills/validator-generator/generated_validators; do \
	  if [ -d "$$dir" ]; then \
	    for item in "$$dir"/*; do \
	      [ -e "$$item" ] || continue; \
	      [ "$$(basename "$$item")" = ".gitkeep" ] && continue; \
	      rm -rf "$$item"; \
	    done; \
	  fi; \
	done
	@rm -f .claude/skills/testcase-generator/generated_spec_sheets/~$$*.xlsx 2>/dev/null || true
	@find .claude/skills -type d -name __pycache__ | while read d; do rm -rf "$$d"; done
	@echo "Done. Preserved: tests/, test_data/, src/, config/, skill seeds, received_sources/, received_schemas/, received_spec_sheets/"

clean: clean-allure
	rm -rf __pycache__ .pytest_cache .mypy_cache
