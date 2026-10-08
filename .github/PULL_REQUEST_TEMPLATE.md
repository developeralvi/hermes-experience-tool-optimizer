name: "EBTTO Pull Request Template"

description: "Pull request template for EBTTO"
body:
  - type: markdown
    attributes:
      value: "Thanks for contributing to EBTTO! Please fill in the sections below."

  - type: dropdown
    id: pr_type
    attributes:
      label: PR type
      options:
        - Bug fix
        - New feature
        - Documentation
        - Test
        - Refactor
        - Other
    validations:
      required: true

  - type: textarea
    id: summary
    attributes:
      label: Summary
      description: Describe the change and the problem it solves.

  - type: textarea
    id: changes
    attributes:
      label: Changes
      description: List the key changes.

  - type: textarea
    id: test_plan
    attributes:
      label: Test plan
      description: How did you verify the change?

  - type: textarea
    id: coverage
    attributes:
      label: Testing done
      description: Which tests were added/updated?

  - type: checkboxes
    id: checks
    attributes:
      label: Checks
      description: Confirm all of the following.
      options:
        - label: Tests added/updated for the change
        - label: `pytest -q` passes locally
        - label: No new secrets or author-specific paths
        - label: `codegraph` index is up to date (if source changed)
        - label: `git log` shows clear, real commits

  - type: textarea
    id: docs
    attributes:
      label: Documentation
      description: Any docs added/updated?
