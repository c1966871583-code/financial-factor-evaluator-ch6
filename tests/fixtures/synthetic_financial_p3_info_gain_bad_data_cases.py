from backend.amr.financial_p3_info_gain_bad_data_gate import BadDataCase
def make_corpus():return (
 BadDataCase("missing_field","missing required financial field","fail_fast","record",{"required_fields":["net_profit"],"record":{}}),
 BadDataCase("type_error","financial field has incompatible type","fail_fast","record",{"required_fields":["net_profit"],"record":{"net_profit":"x"},"field_types":{"net_profit":"float"}}),
 BadDataCase("duplicate_primary_key","duplicate security-date primary key","record_isolated","record",{"primary_keys":[("000001","2024-01-01"),("000001","2024-01-01")]}),
 BadDataCase("many_to_many_join","many-to-many join expansion","record_isolated","record",{"left_join_rows":2,"right_join_rows":2,"expected_join_rows":2}),
 BadDataCase("nonfinite_and_denominator","NaN, inf, zero and epsilon denominator","record_isolated","record",{"values":[float("nan"),float("inf")],"denominators":[0.0,1e-14],"denominator_epsilon":1e-12}),
 BadDataCase("pit_time_violation","PIT availability later than evaluation cutoff","task_blocked","task",{"availability_at":"2024-02-02","cutoff_at":"2024-02-01"}),
 BadDataCase("revision_leakage","restated value visible before permitted revision time","task_blocked","task",{"revision_at":"2024-02-02","cutoff_at":"2024-02-01"}),
 BadDataCase("insufficient_and_constant_cross_section","insufficient sample and constant cross-section","period_not_evaluable","period",{"period_rows":2,"minimum_rows":3,"cross_section":[1.0,1.0]}),
 BadDataCase("labels_and_future_window","missing label or incomplete future window","period_not_evaluable","period",{"labels":[None],"future_window_rows":1,"required_future_rows":2}),
 BadDataCase("f_track_not_evaluable","F evaluation context not frozen","track_not_evaluable","track",{"track":"F","context_frozen":False}),
 BadDataCase("r_no_positive","R track has no positive labels","track_not_evaluable","track",{"track":"R","labels":[0,0]}),
 BadDataCase("r_no_negative","R track has no negative labels","track_not_evaluable","track",{"track":"R","labels":[1,1]}),
 BadDataCase("r_unlabeled","R track is unlabeled","track_not_evaluable","track",{"track":"R","labels":[None,None]}),
 BadDataCase("common_sample_drift","common sample fingerprint, rows, or periods drift","task_blocked","task",{"frozen_fingerprint":"a","actual_fingerprint":"b","frozen_rows":900,"actual_rows":899,"frozen_periods":18,"actual_periods":18}),
 BadDataCase("contract_conflict","frozen contract hash conflicts","task_blocked","task",{"frozen_contract":"a","actual_contract":"b"}),)
