from typing import cast

from django.db import transaction
from django.tasks import ResultStatus, default_task_backend, tasks
from django.tasks.backends.immediate import ImmediateBackend
from django.tasks.exceptions import InvalidTaskError
from django.tasks.task import Task
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone

from . import tasks as test_tasks


@override_settings(
    TASKS={"default": {"BACKEND": "django.tasks.backends.immediate.ImmediateBackend"}}
)
class ImmediateBackendTestCase(SimpleTestCase):
    def test_using_correct_backend(self):
        self.assertEqual(default_task_backend, tasks["default"])
        self.assertIsInstance(tasks["default"], ImmediateBackend)

    def test_enqueue_task(self):
        for task in [test_tasks.noop_task, test_tasks.noop_task_async]:
            with self.subTest(task):
                result = cast(Task, task).enqueue(1, two=3)

                self.assertEqual(result.status, ResultStatus.COMPLETE)
                self.assertIsNotNone(result.started_at)
                self.assertIsNotNone(result.finished_at)
                self.assertGreaterEqual(
                    result.started_at, result.enqueued_at
                )  # type:ignore[arg-type, misc]
                self.assertGreaterEqual(
                    result.finished_at, result.started_at
                )  # type:ignore[arg-type, misc]
                self.assertIsNone(result.return_value)
                self.assertEqual(result.task, task)
                self.assertEqual(result.args, [1])
                self.assertEqual(result.kwargs, {"two": 3})

    async def test_enqueue_task_async(self):
        for task in [test_tasks.noop_task, test_tasks.noop_task_async]:
            with self.subTest(task):
                result = await cast(Task, task).aenqueue()

                self.assertEqual(result.status, ResultStatus.COMPLETE)
                self.assertIsNotNone(result.started_at)
                self.assertIsNotNone(result.finished_at)
                self.assertGreaterEqual(
                    result.started_at, result.enqueued_at
                )  # type:ignore[arg-type, misc]
                self.assertGreaterEqual(
                    result.finished_at, result.started_at
                )  # type:ignore[arg-type, misc]
                self.assertIsNone(result.return_value)
                self.assertEqual(result.task, task)
                self.assertEqual(result.args, [])
                self.assertEqual(result.kwargs, {})

    def test_catches_exception(self):
        test_data = [
            (
                test_tasks.failing_task_value_error,  # task function
                ValueError,  # expected exception
                "This task failed due to ValueError",  # expected message
            ),
            (
                test_tasks.failing_task_system_exit,
                SystemExit,
                "This task failed due to SystemExit",
            ),
        ]
        for task, exception, message in test_data:
            with (
                self.subTest(task),
                self.assertLogs("django.tasks", level="ERROR") as captured_logs,
            ):
                result = task.enqueue()

                # assert logging
                self.assertEqual(len(captured_logs.output), 1)
                self.assertIn(message, captured_logs.output[0])

                # assert result
                self.assertEqual(result.status, ResultStatus.FAILED)
                self.assertIsNotNone(result.started_at)
                self.assertIsNotNone(result.finished_at)
                self.assertGreaterEqual(
                    result.started_at, result.enqueued_at
                )  # type:ignore[arg-type, misc]
                self.assertGreaterEqual(
                    result.finished_at, result.started_at
                )  # type:ignore[arg-type, misc]
                self.assertIsInstance(result.exception, exception)
                self.assertTrue(
                    result.traceback
                    and result.traceback.endswith(f"{exception.__name__}: {message}\n")
                )
                self.assertEqual(result.task, task)
                self.assertEqual(result.args, [])
                self.assertEqual(result.kwargs, {})

    def test_throws_keyboard_interrupt(self):
        with self.assertRaises(KeyboardInterrupt):
            with self.assertLogs("django.tasks", level="ERROR") as captured_logs:
                default_task_backend.enqueue(
                    test_tasks.failing_task_keyboard_interrupt, [], {}
                )

        # assert logging
        self.assertEqual(len(captured_logs.output), 0)

    def test_complex_exception(self):
        with self.assertLogs("django.tasks", level="ERROR"):
            result = test_tasks.complex_exception.enqueue()

        self.assertEqual(result.status, ResultStatus.FAILED)
        self.assertIsNotNone(result.started_at)
        self.assertIsNotNone(result.finished_at)
        self.assertGreaterEqual(
            result.started_at, result.enqueued_at
        )  # type:ignore[arg-type,misc]
        self.assertGreaterEqual(
            result.finished_at, result.started_at
        )  # type:ignore[arg-type,misc]

        self.assertIsNone(result._return_value)
        self.assertIsNone(result.traceback)

        self.assertEqual(result.task, test_tasks.complex_exception)
        self.assertEqual(result.args, [])
        self.assertEqual(result.kwargs, {})

    def test_result(self):
        result = default_task_backend.enqueue(
            test_tasks.calculate_meaning_of_life, [], {}
        )

        self.assertEqual(result.status, ResultStatus.COMPLETE)
        self.assertEqual(result.return_value, 42)

    async def test_result_async(self):
        result = await default_task_backend.aenqueue(
            test_tasks.calculate_meaning_of_life, [], {}
        )

        self.assertEqual(result.status, ResultStatus.COMPLETE)
        self.assertEqual(result.return_value, 42)

    async def test_cannot_get_result(self):
        with self.assertRaisesMessage(
            NotImplementedError,
            "This backend does not support retrieving or refreshing results.",
        ):
            default_task_backend.get_result("123")

        with self.assertRaisesMessage(
            NotImplementedError,
            "This backend does not support retrieving or refreshing results.",
        ):
            await default_task_backend.aget_result(123)  # type:ignore[arg-type]

    async def test_cannot_refresh_result(self):
        result = await default_task_backend.aenqueue(
            test_tasks.calculate_meaning_of_life, (), {}
        )

        with self.assertRaisesMessage(
            NotImplementedError,
            "This backend does not support retrieving or refreshing results.",
        ):
            await result.arefresh()

        with self.assertRaisesMessage(
            NotImplementedError,
            "This backend does not support retrieving or refreshing results.",
        ):
            result.refresh()

    def test_cannot_pass_run_after(self):
        with self.assertRaisesMessage(
            InvalidTaskError,
            "Backend does not support run_after",
        ):
            default_task_backend.validate_task(
                test_tasks.failing_task_value_error.using(run_after=timezone.now())
            )

    def test_enqueue_on_commit(self):
        self.assertFalse(
            default_task_backend._get_enqueue_on_commit_for_task(
                test_tasks.enqueue_on_commit_task
            )
        )

    def test_enqueue_logs(self):
        with self.assertLogs("django.tasks", level="DEBUG") as captured_logs:
            result = test_tasks.noop_task.enqueue()

        self.assertIn("enqueued", captured_logs.output[0])
        self.assertIn(result.id, captured_logs.output[0])


class ImmediateBackendTransactionTestCase(TransactionTestCase):
    @override_settings(
        TASKS={
            "default": {
                "BACKEND": "django.tasks.backends.immediate.ImmediateBackend",
                "ENQUEUE_ON_COMMIT": True,
            }
        }
    )
    def test_wait_until_transaction_commit(self):
        self.assertTrue(default_task_backend.enqueue_on_commit)
        self.assertTrue(
            default_task_backend._get_enqueue_on_commit_for_task(test_tasks.noop_task)
        )

        with transaction.atomic():
            result = test_tasks.noop_task.enqueue()

            self.assertIsNone(result.enqueued_at)
            self.assertEqual(result.status, ResultStatus.NEW)

        self.assertEqual(result.status, ResultStatus.COMPLETE)
        self.assertIsNotNone(result.enqueued_at)

    @override_settings(
        TASKS={
            "default": {
                "BACKEND": "django.tasks.backends.immediate.ImmediateBackend",
                "ENQUEUE_ON_COMMIT": False,
            }
        }
    )
    def test_doesnt_wait_until_transaction_commit(self):
        self.assertFalse(default_task_backend.enqueue_on_commit)
        self.assertFalse(
            default_task_backend._get_enqueue_on_commit_for_task(test_tasks.noop_task)
        )

        with transaction.atomic():
            result = test_tasks.noop_task.enqueue()

            self.assertIsNotNone(result.enqueued_at)

            self.assertEqual(result.status, ResultStatus.COMPLETE)

        self.assertEqual(result.status, ResultStatus.COMPLETE)

    @override_settings(
        TASKS={
            "default": {
                "BACKEND": "django.tasks.backends.immediate.ImmediateBackend",
            }
        }
    )
    def test_wait_until_transaction_by_default(self):
        self.assertTrue(default_task_backend.enqueue_on_commit)
        self.assertTrue(
            default_task_backend._get_enqueue_on_commit_for_task(test_tasks.noop_task)
        )

        with transaction.atomic():
            result = test_tasks.noop_task.enqueue()

            self.assertIsNone(result.enqueued_at)
            self.assertEqual(result.status, ResultStatus.NEW)

        self.assertEqual(result.status, ResultStatus.COMPLETE)

    @override_settings(
        TASKS={
            "default": {
                "BACKEND": "django.tasks.backends.immediate.ImmediateBackend",
                "ENQUEUE_ON_COMMIT": False,
            }
        }
    )
    def test_task_specific_enqueue_on_commit(self):
        self.assertFalse(default_task_backend.enqueue_on_commit)
        self.assertTrue(test_tasks.enqueue_on_commit_task.enqueue_on_commit)
        self.assertTrue(
            default_task_backend._get_enqueue_on_commit_for_task(
                test_tasks.enqueue_on_commit_task
            )
        )

        with transaction.atomic():
            result = test_tasks.enqueue_on_commit_task.enqueue()

            self.assertIsNone(result.enqueued_at)
            self.assertEqual(result.status, ResultStatus.NEW)

        self.assertEqual(result.status, ResultStatus.COMPLETE)
