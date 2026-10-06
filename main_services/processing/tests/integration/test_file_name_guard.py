"""Verify the filename payload limits through the worker interceptor."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, UnsandboxedWorkflowRunner

from tasks.P2_execute_plan.activities import DownloadPlanFilesParams
from tasks.P2_execute_plan.workflows import ProcessItemsBatchedParams, PLAN_GROUP_SIZE, MAX_PLAN_DRIVERS
from tasks.P3_parse_files.file_names import bounded_file_names
from tasks.payload_guard import PayloadGuardInterceptor


@activity.defn(name="verify_filename_download")
def download(params: DownloadPlanFilesParams) -> int:
    assert len(params.items) == 1000
    assert all('file_names' not in item for item in params.items)
    return len(params.items)


@workflow.defn
class NamedGroup:
    @workflow.run
    async def run(self, params: ProcessItemsBatchedParams) -> int:
        assert all(item['file_names'] for item in params.items)
        return len(params.items)


@workflow.defn
class NamedPlan:
    @workflow.run
    async def run(self, params: dict) -> int:
        await workflow.execute_activity(download, DownloadPlanFilesParams(**params['download']),
                                        start_to_close_timeout=timedelta(seconds=30))
        return sum(await asyncio.gather(*[
            workflow.execute_child_workflow(NamedGroup.run, ProcessItemsBatchedParams(**group),
                id=f'{workflow.info().workflow_id}-{index}')
            for index, group in enumerate(params['groups'])]))


def test_filename_payloads_through_worker_guard():
    async def run():
        async with await WorkflowEnvironment.start_time_skipping() as env:
            with ThreadPoolExecutor(4) as executor:
                async with Worker(env.client, task_queue='filename-guard',
                    workflows=[NamedPlan, NamedGroup], activities=[download],
                    activity_executor=executor, workflow_runner=UnsandboxedWorkflowRunner(),
                    interceptors=[PayloadGuardInterceptor()]):
                    for stem in ['a', '"', '\\', 'é', '文', '😀', '\x01', '\n']:
                        collection = 'c' * 48
                        dataset = collection + '_' + 'd' * 48
                        names = bounded_file_names([stem * 255 + ext for ext in ['.eml', '.vcf', '.txt', '.csv']])
                        items = [{'item_hash': f'{i:064x}', 'file_size_bytes': 123456789,
                                  's3_url': f's3://hoover4-c-{collection}/{dataset}/{i:064x}', 'file_names': names}
                                 for i in range(1000)]
                        dl = DownloadPlanFilesParams(collection, dataset, 'f' * 40,
                            [{k: v for k, v in item.items() if k != 'file_names'} for item in items],
                            '/tmp/hoover4-processing')
                        groups = [ProcessItemsBatchedParams(collection, dataset, 'f' * 40,
                            f'/tmp/hoover4-processing/{dataset}/' + 'f' * 40,
                            items[i:i + PLAN_GROUP_SIZE], 'o' * 36).__dict__
                            for i in range(0, 1000, PLAN_GROUP_SIZE)][:MAX_PLAN_DRIVERS]
                        result = await env.client.execute_workflow(NamedPlan.run,
                            {'download': dl.__dict__, 'groups': groups}, id=str(uuid4()),
                            task_queue='filename-guard', execution_timeout=timedelta(seconds=60))
                        assert result == sum(len(group['items']) for group in groups)
    asyncio.run(run())
