    - task: Bash@3
      displayName: Run GCP Smoke Test
      inputs:
          targetType: inline
          script: |
              export AUTH_TOKEN=$(gcloud auth print-access-token)
              python3 ${{ parameters.repo }}/templates/utils/gcp_smoke_test_framework/main.py
              exit_code=$?
              echo "Exit code: $exit_code"
          failOnStderr: true
      env:
          SMOKE_TEST_PATH: ${{ parameters.SMOKE_TEST_PATH }}


Exit code: 0
##[error]Bash wrote one or more lines to the standard error stream.
##[error]Test Passed: Sample-test
2024-01-12 13:27:47,619 - INFO - Test Passed: Sample-test

##[error]Test Passed: ComplexResponseTest
2024-01-12 13:27:47,620 - INFO - Test Passed: ComplexResponseTest
Test Execution Summary: 2 tests executed, 2 tests passed, 0 tests failed
2024-01-12 13:27:47,620 - INFO - Test Execution Summary: 2 tests executed, 2 tests passed, 0 tests failed
