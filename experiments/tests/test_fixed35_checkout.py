import pytest


def test_evaluator_checkout_matches_actual_loaded_code_commit_and_clean_tree(tmp_path,monkeypatch):
    import memweave_eval.fixed35_campaign as campaign
    from memweave_eval.fixed35_campaign import verify_evaluator_checkout
    module=tmp_path/'experiments/src/memweave_eval/fixed35_campaign.py';module.parent.mkdir(parents=True);module.write_text('# unit only')
    monkeypatch.setattr(campaign,'__file__',str(module))
    observed=[];state={'root':str(tmp_path),'head':'a'*40,'status':''}
    def git(command,**kwargs):
        observed.append(command)
        if '--show-toplevel'in command:return state['root']+'\n'
        if 'rev-parse'in command:return state['head']+'\n'
        return state['status']
    monkeypatch.setattr(campaign.subprocess,'check_output',git)
    record={'code_path':str(tmp_path),'evaluator_commit':'a'*40}
    verify_evaluator_checkout(record)
    assert all('-C'in command and command[command.index('-C')+1]==str(tmp_path)for command in observed)
    assert any('--no-optional-locks'in command for command in observed)
    for key,value in [('head','b'*40),('status',' M experiments/src/grader.py\n'),('root',str(tmp_path.parent))]:
        previous=state[key];state[key]=value
        with pytest.raises(ValueError):verify_evaluator_checkout(record)
        state[key]=previous
    with pytest.raises(ValueError):verify_evaluator_checkout(dict(record,evaluator_commit='short'))
    monkeypatch.setattr(campaign,'__file__',str(tmp_path.parent/'other/eval.py'))
    with pytest.raises(ValueError,match='loaded'):verify_evaluator_checkout(record)


def test_git_verification_failure_never_passes_or_changes_files(tmp_path,monkeypatch):
    import memweave_eval.fixed35_campaign as campaign
    from memweave_eval.fixed35_campaign import verify_evaluator_checkout
    module=tmp_path/'experiments/src/memweave_eval/fixed35_campaign.py';module.parent.mkdir(parents=True);module.write_text('unchanged')
    monkeypatch.setattr(campaign,'__file__',str(module))
    def denied(*args,**kwargs):raise PermissionError('unit permission rejection')
    monkeypatch.setattr(campaign.subprocess,'check_output',denied)
    with pytest.raises(ValueError,match='verified'):verify_evaluator_checkout({'code_path':str(tmp_path),'evaluator_commit':'a'*40})
    assert module.read_text()=='unchanged'
