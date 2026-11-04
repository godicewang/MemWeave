from memweave_eval.engineering_metrics import episode_phase_seconds, episode_telemetry


def test_cpu_sums_each_producer_max_not_all_cumulative_samples_or_last_stage():
    def ready(r,p,c,rss):return {'event':'request_ready','request_id':r,'producer_id':p,'process_usage':{'userCPUTime':c,'systemCPUTime':0,'maxRSS':rss}}
    events=[ready('a','p1',10,20),ready('b','p1',30,40),ready('c','p2',50,60)]
    transport=[]
    for i,r in enumerate(['a','b','c']):
        transport.extend([{'event':'http_attempt','request_id':r,'timestamp':f'2026-11-04T00:00:0{i}+00:00'},
            {'event':'request_end','request_id':r,'timestamp':f'2026-11-04T00:00:0{i+1}+00:00'}])
    result=episode_telemetry(events,transport,{'a','b','c'})
    assert result['pi_process_cpu_seconds']==80/1000000
    assert result['pi_process_peak_rss_kb']==60 and result['resource_producers']==2
    assert result['request_wall_seconds']['p50']==1
    cas=[{k:v for k,v in e.items()if k!='process_usage'}for e in events]
    assert episode_telemetry(cas,[*transport,*events],{'a','b','c'})['pi_process_cpu_seconds']==80/1000000
    assert episode_telemetry(events[:-1],transport,{'a','b','c'})['pi_process_cpu_seconds']is None
    assert episode_telemetry(events,transport[:-1],{'a','b','c'})['request_wall_seconds']['p50']is None


def test_phase_times_use_original_step_intervals_when_parent_is_null():
    phase={'started_at':'2026-11-04T00:00:00Z','finished_at':'2026-11-04T00:00:03Z'}
    raw={'agent_execution':None,'environment_setup':phase,'step_results':[{'agent_execution':phase},{'agent_execution':phase}]}
    result=episode_phase_seconds(raw)
    assert result['agent_execution']==6 and result['environment_setup']==3
    assert result['verifier']is None
    raw['step_results'][1]['agent_execution']=None
    assert episode_phase_seconds(raw)['agent_execution']is None
