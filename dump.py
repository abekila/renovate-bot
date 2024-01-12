from tests.gcp_workflow_test import GCPWorkflowTest
import logging

class TestExecutor:
    def __init__(self, config):
        self.config = config
        self.test_classes = {'Cloud-Workflow': GCPWorkflowTest}
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(logging.StreamHandler())

    def execute(self):
        test_results = []

        for resource_item in self.config:
            resource_type = resource_item.resource_type
            test_class = self.test_classes.get(resource_type)

            if test_class:
                results = self.execute_tests_for_resource(test_class, resource_item)
                self.logger.debug(f"Results from test class {test_class.__name__} for {resource_item}: {results}")
                test_results.extend(results)
            else:
                self.logger.error(f"No test class found for resource type: {resource_type}")

        # Initialize counters
        passed_tests = 0
        failed_tests = 0

        # Process each test result to determine the summary
        all_tests_passed = True

        # Process each test result to determine the summary
        all_tests_passed = True

        for result in test_results:
            if all(assertion["result"] for assertion in result.get('assertion_results', [])):
                passed_tests += 1
                self.logger.info(f"Test Passed: {result.get('test_name', 'Unknown')}")
            else:
                all_tests_passed = False
                failed_tests += 1
                self.logger.error(f"Test Failed: {result.get('test_name', 'Unknown')} - {result.get('details', 'No details available')}")
        total_tests = len(test_results)
        self.logger.info(f"Test Execution Summary: {total_tests} tests executed, {passed_tests} tests passed, {failed_tests} tests failed")

        return all_tests_passed

    def execute_tests_for_resource(self, test_class, resource_item):
        aggregated_results = []
        for test_config in resource_item.tests:
            test_instance = test_class(test_config, resource_item)
            try:
                test_results = test_instance.run()
                self.logger.debug(f"Raw result from test instance: {test_results}")
                for result in test_results:
                    result.setdefault('test_name', test_config.test_name)
                aggregated_results.extend(test_results)
            except Exception as e:
                self.logger.error(f"An error occurred while executing the test: {str(e)}")
                error_result = {"status": "Failed", "details": str(e), "test_name": test_config.test_name}
                aggregated_results.append(error_result)

        self.logger.debug(f"Final aggregated results: {aggregated_results}")
        return aggregated_results




###################################GCPWORKFLOWTEST######################
import requests
import json
import time
from .base_test import BaseTest
from assertion.assertions import AssertionUtility
from utils.pre_process import DataNormalizer
from concurrent.futures import ThreadPoolExecutor, as_completed
from config.models import Assertion
from utils.retrieval import get_nested_value
import  settings
import os

class GCPWorkflowTest(BaseTest):
    def __init__(self, test_config, resource_config):
        super().__init__(resource_config)
        self.workflows = test_config.workflows
        self.auth_token = self.get_auth_token()
        # Initial debug log
        self.logger.debug("Starting run method in GCPWorkflowTest")

        # Simplified result for testing
        test_result = {"workflow": "TestWorkflow", "status": "Succeeded", "details": "Test passed", "test_name": "SimplifiedTest"}
        
        # Log the simplified result
        self.logger.debug(f"Returning simplified test result: {test_result}")

    def get_auth_token(self):
        """
        Get the authentication token from an environment variable.

        Returns:
            str: The authentication token.

        Raises:
            AuthTokenMissingError: If the authentication token is not found.
        """
        token = os.environ.get("AUTH_TOKEN")
        if token is None:
            self.logger.error("Authentication token not found. Please set the AUTH_TOKEN environment variable.")
            raise Exception("Authentication token not found.")
        return token

    def trigger_workflow_execution(self, workflow_name):
        endpoint = f"https://workflowexecutions.googleapis.com/v1/projects/{self.resource_config.project_id}/locations/{self.resource_config.location}/workflows/{workflow_name}/executions"
        headers = {"Authorization": f"Bearer {self.auth_token}", "Content-Type": "application/json"}
        response = requests.post(endpoint, headers=headers, data=json.dumps({}))
        if response.status_code == 200:
            return response.json()['name']
        else:
            self.logger.error(f"Failed to trigger workflow {workflow_name}: {response.text}")
            raise Exception(f"Failed to trigger workflow {workflow_name}")

    def get_workflow_execution(self, execution_name):
        endpoint = f"https://workflowexecutions.googleapis.com/v1/{execution_name}"
        headers = {"Authorization": f"Bearer {self.auth_token}", "Content-Type": "application/json"}
        response = requests.get(endpoint, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            self.logger.error(f"Failed to get execution details for {execution_name}: {response.text}")
            raise Exception(f"Failed to get execution details for {execution_name}")

    def wait_for_workflow_completion(self, execution_name, workflow_config):
        retry_delay = workflow_config.retry_delay
        max_delay = workflow_config.max_delay
        max_retries = workflow_config.max_retries
        timeout_seconds = workflow_config.timeout

        retry_count = 0
        start_time = time.time()

        while retry_count < max_retries and time.time() - start_time < timeout_seconds:
            try:
                execution_details = self.get_workflow_execution(execution_name)
                state = execution_details.get('state')

                if state in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
                    return execution_details

                self.logger.info(f"Workflow '{execution_name}' is in state '{state}'. "
                                 f"Retry {retry_count+1}/{max_retries}, next attempt in {retry_delay} seconds.")

                retry_count += 1
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_delay)

            except requests.exceptions.RequestException as e:
                self.logger.error(f"Failed to get execution details for workflow '{execution_name}': {str(e)}")
                self.logger.info(f"Retry {retry_count+1}/{max_retries}, next attempt in {retry_delay} seconds.")

                retry_count += 1
                time.sleep(min(retry_delay, max_delay))
                retry_delay = min(retry_delay * 2, max_delay)

        if retry_count >= max_retries:
            self.logger.error(f"Maximum retries reached for workflow execution {execution_name}.")
            raise TimeoutError(f"Maximum retries reached for workflow execution {execution_name}.")

        # Raise a timeout error if the workflow did not complete within the allotted time
        raise TimeoutError(f"Workflow execution {execution_name} did not complete within the specified timeout period.")

    def assert_workflow_execution(self, execution_details, assertions, workflow_name):
        normalized_data = DataNormalizer().normalize_data(execution_details)
        assertion_results = []
        strategy_map = AssertionUtility.assert_strategy_map()

        for assertion in assertions:
            key_path = assertion.key
            actual_value = get_nested_value(normalized_data, key_path)
            data_type = assertion.data_type
            method = assertion.method
            assert_method = strategy_map.get((data_type, method))

            if not assert_method:
                assertion_results.append({
                    "result": False,
                    "message": f"Unknown assertion strategy: {data_type}, {method} in workflow '{workflow_name}'",
                    "key": key_path
                })
                continue

            try:
                # Execute the assertion
                if method in ["truthy", "falsy"]:
                    assert_method(actual_value, key_path)
                else:
                    assert_method(actual_value, assertion.expected, key_path)
                assertion_results.append({
                    "result": True,
                    "message": f"Assertion passed for key '{key_path}'",
                    "key": key_path
                })

            except AssertionError as ae:
                assertion_results.append({
                    "result": False,
                    "message": f"Assertion failed for key '{key_path}': {str(ae)}",
                    "key": key_path
                })

        return assertion_results

    def test_workflow(self, workflow_config):
        workflow_name = workflow_config.name
        result = {
            "workflow": workflow_name,
            "status": None,
            "details": "",
            "name": None,
            "startTime": None,
            "endTime": None,
            "duration": None,
            "state": None,
            "argument": None,
            "result": None,
            "error": None,
            "workflowRevisionId": None,
            "callLogLevel": None,
            "stateError": None,
            "assertion_results": []
        }
        try:
            execution_name = self.trigger_workflow_execution(workflow_name)
            execution_details = self.wait_for_workflow_completion(execution_name, workflow_config)

            # Update result with execution details from the Workflow REST API
            result.update(execution_details)

            # Perform and store structured assertion results
            assertion_results = self.assert_workflow_execution(execution_details, workflow_config.assertions, workflow_name)
            result['assertion_results'] = assertion_results
            # Determine overall test status
            failed_assertions = any(not res["result"] for res in assertion_results)
            result["status"] = "Failed" if failed_assertions else execution_details.get('state', 'Unknown')
        except Exception as e:
            result["details"] = str(e)
            result["status"] = "Failed"

        return result

    def run(self):
        results = []
        with ThreadPoolExecutor(max_workers=len(self.workflows)) as executor:
            futures = {executor.submit(self.test_workflow, workflow): workflow.name for workflow in self.workflows}
            for future in as_completed(futures):
                workflow_name = futures[future]
                try:
                    result = future.result()
                    self.logger.debug(f"Result for workflow '{workflow_name}': {result}")  # Debugging
                    results.append(result)
                except Exception as exc:
                    self.logger.error(f"{workflow_name} generated an exception: {exc}")
                    results.append({"workflow": workflow_name, "status": "Error", "details": str(exc)})
                    self.logger.debug(f"Error result for workflow '{workflow_name}': {results[-1]}")  # Debugging

        # Generate and print a formatted summary report
        print("Test Summary Report:\n")
        for res in results:
            print(f"Workflow: {res['workflow']}\n"
                  f"  Test Status: {res['status']}\n"
                  f"  Name: {res.get('name')}\n"
                  f"  Start Time: {res.get('startTime')}\n"
                  f"  End Time: {res.get('endTime')}\n"
                  f"  Duration: {res.get('duration')}\n"
                  f"  Workflow State: {res.get('state')}\n"
                  f"  Argument: {res.get('argument')}\n"
                  f"  Result: {res.get('result')}\n"
                  f"  Error: {res.get('error')}\n"
                  f"  Workflow Revision ID: {res.get('workflowRevisionId')}\n"
                  f"  Call Log Level: {res.get('callLogLevel')}\n"
                  f"  State Error: {res.get('stateError')}\n"
                  f"  Details: {res['details']}\n")
            for assertion_result in res.get('assertion_results', []):
                print(f"    - {assertion_result}")
            print("\n")
        self.logger.debug(f"Final aggregated results in run(): {results}")  # Debugging
        return results

#####################################MAINN################
    
import sys
import os
import logging

def setup_logging():
    """
    Set up logging configuration to debug level.
    """
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def get_root_directory():
    """
    Determine the root directory of the project.
    """
    return os.path.dirname(os.path.abspath(__file__))

def add_root_to_path(root_directory):
    """
    Add the root directory to the Python path.
    """
    sys.path.append(root_directory)

def get_yaml_file_path(root_directory):
    """
    Get the YAML file path from environment variable or default location.
    """
    return os.path.join(os.environ.get("SMOKE_TEST_PATH", root_directory), "smoke_test.yaml")

def main():
    setup_logging()
    try:
        from config.config_loader import ConfigLoader
        from executor.test_executor import TestExecutor

        root_directory = get_root_directory()
        add_root_to_path(root_directory)

        yaml_file_path = get_yaml_file_path(root_directory)
        loader = ConfigLoader(yaml_file_path)
        config = loader.load_and_validate()

        executor = TestExecutor(config)
        success = executor.execute()

        if not success:
            sys.exit(1)  # Exit with a non-zero code to indicate failure

    except Exception as e:
        logging.error(f"Error in main execution: {e}", exc_info=True)

if __name__ == "__main__":
    main()

asdasd
