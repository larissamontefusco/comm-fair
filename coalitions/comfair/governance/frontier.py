"""Candidate-policy nondominance and explicit lexicographic demo selection."""


def frontier(candidates, y_key, money_tolerance, share_tolerance):
    def y(row):
        return row['metrics']['inequality']['gini']['value'] if y_key=='gini' else row['metrics']['contribution_share_L1_distance']
    result={}
    for a in candidates:
        av=y(a);dominators=[]
        if av is not None:
            for b in candidates:
                bv=y(b)
                if a['policy_id']==b['policy_id'] or bv is None:continue
                ax=a['metrics']['market_L1_distance_aud'];bx=b['metrics']['market_L1_distance_aud']
                if bx<=ax+money_tolerance and bv<=av+share_tolerance and (bx<ax-money_tolerance or bv<av-share_tolerance):
                    dominators.append(b['policy_id'])
        result[a['policy_id']]={'status':'incomparable' if av is None else 'dominated' if dominators else 'nondominated',
            'dominated_by':sorted(dominators),'x_market_L1_aud':a['metrics']['market_L1_distance_aud'],'y':av,
            'minimum_benefit_aud':a['metrics']['minimum_benefit_aud']}
    return result


def select_demo(candidates, money_tolerance, share_tolerance):
    pool=sorted((x for x in candidates if x['metrics']['constitutionally_admissible']),key=lambda x:x['policy_id'])
    if not pool:raise ValueError('No admissible governance candidate')
    trace=[{'step':'constitution','remaining':[x['policy_id'] for x in pool]}]
    for key,minimise,tol in [('market_L1_distance_aud',True,money_tolerance),('minimum_benefit_aud',False,money_tolerance),('contribution_share_L1_distance',True,share_tolerance)]:
        valid=[x['metrics'][key] for x in pool if x['metrics'][key] is not None]
        if valid:
            best=min(valid) if minimise else max(valid)
            pool=[x for x in pool if x['metrics'][key] is not None and abs(x['metrics'][key]-best)<=tol]
        else:best=None
        trace.append({'step':key,'best':best,'tolerance':tol,'remaining':[x['policy_id'] for x in pool],
                      'undefined_rule':'skip criterion if all undefined; otherwise retain defined candidates'})
    selected=pool[0]['policy_id'];trace.append({'step':'lexical_policy_id','selected':selected})
    return {'policy_id':selected,'role':'minimal-intervention default for demonstration','universally_fairest':False,'trace':trace}
