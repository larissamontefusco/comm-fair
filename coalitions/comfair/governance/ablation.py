"""A0-A5 keeps physical creation, settlement, repair and governance distinct."""


def build_ablation(inputs, policies, candidates, demo):
    m3,m6=inputs.m3,inputs.m6
    lookup={p['policy_id']:p for p in policies}
    final=next(c for c in candidates if c['policy_id']==demo['policy_id'])
    required={int(i):x for i,x in m6['coalition']['witness']['benefit_aud'].items()}
    chosen=final['metrics']['benefits_aud']
    governance_tau={i:required[i]-chosen[i] for i in required}
    return {'stages':[
        {'stage':'A0','description':'Standalone outside options','community_cost_aud':m3['sum_B_i_aud'],
         'bills_aud':m3['B_i_aud'],'cooperative_surplus_aud':None,'allocation_metrics':None,
         'not_applicable_reason':'No cooperative operation or cooperative allocation yet'},
        {'stage':'A1','description':'Physical cooperation creates surplus','community_cost_aud':m3['C_N_aud'],
         'cooperative_surplus_aud':m3['v_N_aud'],'allocation_metrics':None,'not_applicable_reason':'No member settlement yet'},
        {'stage':'A2','description':'M4 market allocates surplus','metrics':lookup['P0_protected_marginal']['raw']},
        {'stage':'A3','description':'Minimum individual participation repair','source':'exact canonical M6 IR witness',
         'r_IR_aud':m6['individual']['r_IR_aud'],'epsilon_IR_aud':m6['coalition']['epsilon_IR_aud'],
         'witness':m6['individual']['witness'],'epsilon_IR_witness':m6['coalition']['epsilon_IR_witness']},
        {'stage':'A4','description':'Minimum coalition resilience repair','source':'exact canonical M6 CR witness',
         'r_CR_aud':m6['coalition']['r_CR_aud'],'CRP_aud':m6['coalition']['CRP_aud'],'RSG_aud':m6['coalition']['RSG_aud'],
         'epsilon_star_aud':m6['coalition']['epsilon_star_m5_aud'],'witness':m6['coalition']['witness']},
        {'stage':'A5','description':'Optional normative governance choice','selected_policy':demo['policy_id'],
         'metrics':final['metrics'],'governance_transfer_from_A4_aud':governance_tau,
         'all_admissible_alternatives':[c['policy_id'] for c in candidates],
         'necessary_repair_source':'M6; governance transfer is separately labelled'}],
        'scope':'Fixed physical dispatch; allocation analysis, not an economic-efficiency frontier',
        'm6_repair_curve':{'artifact':'m6_repair_curve.json','sha256':inputs.provenance['upstream_artifact_hashes']['m6_repair_curve.json']}}
