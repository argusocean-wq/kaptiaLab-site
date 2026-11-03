import tempfile
import unittest
from pathlib import Path

from core_foundation import (
    CoreOrchestrator, ExecutionResult, ModelRequest, ModelRouter,
    ModelRoutingError, PlanValidationError, TaskRepository,
    VerificationEngine, build_plan,
)


class PlannerTests(unittest.TestCase):
    def test_builds_valid_dag_and_namespaces_step_ids(self):
        plan = build_plan("Build core", "Create the first core slice", [
            {"step_id": "design", "title": "Design", "objective": "Define contracts"},
            {"step_id": "test", "title": "Test", "objective": "Add tests", "depends_on": ["design"]},
        ])
        self.assertEqual(len(plan.steps), 2)
        self.assertTrue(plan.steps[0].step_id.endswith(":design"))
        self.assertEqual(plan.steps[1].depends_on, (plan.steps[0].step_id,))

    def test_two_plans_can_reuse_human_step_keys(self):
        first = build_plan("First", "First plan", [{"step_id": "build", "title": "Build"}])
        second = build_plan("Second", "Second plan", [{"step_id": "build", "title": "Build"}])
        self.assertNotEqual(first.steps[0].step_id, second.steps[0].step_id)

    def test_rejects_cycle_and_missing_dependency(self):
        with self.assertRaises(PlanValidationError):
            build_plan("Cycle", "Invalid graph", [
                {"step_id": "a", "title": "A", "objective": "A", "depends_on": ["b"]},
                {"step_id": "b", "title": "B", "objective": "B", "depends_on": ["a"]},
            ])
        with self.assertRaises(PlanValidationError):
            build_plan("Missing", "Invalid graph", [
                {"step_id": "a", "title": "A", "objective": "A", "depends_on": ["missing"]},
            ])

    def test_rejects_bad_retry_and_classification(self):
        for extra in ({"max_attempts": True}, {"data_classification": "secret"}):
            with self.assertRaises(PlanValidationError):
                build_plan("Bad", "Invalid", [{"title": "A", "objective": "A", **extra}])


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(Path(self.temp.name) / "tasks.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_dependency_gates_claiming_and_completion(self):
        plan = build_plan("Pipeline", "Run ordered steps", [
            {"step_id": "one", "title": "One", "objective": "First"},
            {"step_id": "two", "title": "Two", "objective": "Second", "depends_on": ["one"]},
        ])
        self.repo.create_plan(plan)
        first = self.repo.claim_ready_steps("worker-a", limit=4)
        self.assertEqual([item["step_id"] for item in first], [plan.steps[0].step_id])
        with self.assertRaises(ValueError):
            self.repo.transition_step(plan.steps[0].step_id, "completed", "Skip verification",
                                      verification={"passed": True})
        self.repo.transition_step(plan.steps[0].step_id, "verifying", "Ready for verification")
        self.repo.transition_step(plan.steps[0].step_id, "completed", "Verified",
                                  verification={"passed": True})
        second = self.repo.claim_ready_steps("worker-a", limit=4)
        self.assertEqual([item["step_id"] for item in second], [plan.steps[1].step_id])

    def test_claiming_is_persistent_and_task_status_updates(self):
        plan = build_plan("Single", "One task", [{"title": "Do", "objective": "Do it"}])
        created = self.repo.create_plan(plan)
        claimed = self.repo.claim_ready_steps("worker-a")
        self.assertEqual(claimed[0]["attempts"], 1)
        self.assertEqual(self.repo.get_task(created["task_id"])["status"], "running")

    def test_invalid_transition_and_retry_limit(self):
        plan = build_plan("Retry", "Retry task", [
            {"title": "Do", "objective": "Do it", "max_attempts": 1}
        ])
        self.repo.create_plan(plan)
        step = self.repo.claim_ready_steps("worker-a")[0]
        self.repo.transition_step(step["step_id"], "failed", "Executor failed")
        with self.assertRaises(ValueError):
            self.repo.retry_failed_step(step["step_id"])

    def test_events_are_auditable(self):
        plan = build_plan("Events", "Record events", [{"title": "Do", "objective": "Do it"}])
        created = self.repo.create_plan(plan)
        self.assertEqual(created["events"][0]["event_type"], "task_created")


class ModelRouterTests(unittest.TestCase):
    class Provider:
        def __init__(self, output=None, error=None):
            self.output = output
            self.error = error

        def generate(self, request):
            if self.error:
                raise self.error
            return self.output

    def test_local_only_never_routes_to_cloud_or_external(self):
        router = ModelRouter(policy="cloud_first")
        router.register("cloud", self.Provider("cloud answer"), location="user_cloud", capabilities={"chat"})
        router.register("local", self.Provider("local answer"), location="local", capabilities={"chat"})
        result = router.generate(ModelRequest("private prompt", required_capabilities=("chat",),
                                              data_classification="local_only"))
        self.assertEqual(result["provider_id"], "local")

    def test_private_data_never_routes_to_third_party_external(self):
        router = ModelRouter(policy="cloud_first")
        router.register("external", self.Provider("external answer"), location="external", capabilities={"chat"})
        router.register("user-cloud", self.Provider("user cloud answer"), location="user_cloud", capabilities={"chat"})
        result = router.generate(ModelRequest("private prompt", required_capabilities=("chat",),
                                              data_classification="private"))
        self.assertEqual(result["provider_id"], "user-cloud")

    def test_fallback_is_explicit_and_capability_filtered(self):
        router = ModelRouter()
        router.register("broken-local", self.Provider(error=RuntimeError("offline")),
                        location="local", capabilities={"chat"})
        router.register("cloud", self.Provider("cloud answer"), location="user_cloud",
                        capabilities={"chat", "vision"})
        result = router.generate(ModelRequest("prompt", required_capabilities=("chat",)))
        self.assertEqual(result["provider_id"], "cloud")
        self.assertTrue(result["fallback_used"])
        with self.assertRaises(ModelRoutingError):
            router.generate(ModelRequest("prompt", required_capabilities=("audio",)))


class VerificationAndOrchestratorTests(unittest.TestCase):
    def test_unknown_check_fails_closed(self):
        result = VerificationEngine().verify("output", [{"type": "arbitrary_python"}])
        self.assertFalse(result.passed)

    def test_empty_contains_all_check_fails_closed(self):
        result = VerificationEngine().verify("anything", [{"type": "contains_all", "values": []}])
        self.assertFalse(result.passed)

    def test_execution_result_rejects_non_text_output(self):
        with self.assertRaises(TypeError):
            ExecutionResult(None)

    def test_verification_blocks_task_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = TaskRepository(Path(tmp) / "tasks.sqlite3")
            orchestrator = CoreOrchestrator(repo)
            plan = build_plan("Verified task", "Must contain OK", [{
                "title": "Produce output", "objective": "Return output",
                "verification": [{"type": "contains_all", "values": ["OK"]}],
            }])
            orchestrator.submit(plan)
            result = orchestrator.run_once("worker-a", lambda step: "not accepted")
            self.assertEqual(result[0]["status"], "failed")
            task = repo.get_task(plan.task_id)
            self.assertEqual(task["status"], "failed")
            self.assertFalse(task["steps"][0]["verification_result"]["passed"])

    def test_success_requires_passed_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = TaskRepository(Path(tmp) / "tasks.sqlite3")
            orchestrator = CoreOrchestrator(repo)
            plan = build_plan("Success", "Must return OK", [{
                "title": "Produce output", "objective": "Return output",
                "verification": [{"type": "contains_all", "values": ["OK"]}],
            }])
            orchestrator.submit(plan)
            result = orchestrator.run_once("worker-a", lambda step: ExecutionResult("OK", evidence={"test": "unit"}))
            self.assertEqual(result[0]["status"], "completed")
            self.assertEqual(repo.get_task(plan.task_id)["status"], "completed")


if __name__ == "__main__":
    unittest.main()
