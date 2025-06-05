import time
from threading import Thread

from logos.classification.classification_manager import ClassificationManager
from logos.classification.proxy_policy import ProxyPolicy
import data
from logos.scheduling.scheduling_fcfs import FCFSScheduler
from logos.scheduling.scheduling_manager import SchedulingManager


def test_scheduling_manager():
    select = ClassificationManager(data.models)
    tasks = select.classify("absolutely no idea", ProxyPolicy())
    tasks = [(2, 387.0, 0), (3, 371.0, 0), (1, 365.0, 0), (2, 365.0, 0), (1, 360.0, 0), (2, 350.0, 0)]
    print(tasks)

    def exec_task(data, models):
        sm = SchedulingManager(FCFSScheduler())
        sm.run()
        tid = sm.add_request(data, models)
        while not sm.is_finished(tid):
            pass

        out = sm.get_result()
        # -- DO SOMETHING --
        if out.models[0][0] == 2:
            time.sleep(1)
        if out.models[0][0] == 1:
            time.sleep(0.5)
        if out is not None:
            print(out.data)
        sm.set_free(out.models[0][0])

    ts = list()
    for task, text in zip(tasks, ["a", "b", "c", "d", "e", "f"]):
        t = Thread(target=exec_task, args=(text, [task]))
        t.start()
        ts.append(t)
    start = time.time()
    while ts:
        ts = [i for i in ts if i.is_alive()]
    print("{:.2f}".format(time.time() - start))

    sm = SchedulingManager(FCFSScheduler())
    sm.stop()


if __name__ == "__main__":
    test_scheduling_manager()
