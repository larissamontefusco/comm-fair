"""Descriptive allocation/justice metrics; metadata never enters optimisation."""
import math
from comfair.game.stability import allocation_diagnostics


def nullable(value=None, reason=None):
    return {'value':value,'reason':reason}


def inequality(benefits, tolerance):
    xs=list(benefits.values());n=len(xs)
    if min(xs)<-tolerance:
        return {'gini':nullable(reason='negative_benefits'),'jain':nullable(reason='negative_benefits')}
    if min(xs)<0:
        return {'gini':nullable(reason='negative_numerical_residual'),'jain':nullable(reason='negative_numerical_residual')}
    total=sum(xs);squares=sum(x*x for x in xs)
    if total<=tolerance:
        return {'gini':nullable(reason='zero_total_benefit'),'jain':nullable(reason='all_zero_within_tolerance')}
    return {'gini':nullable(sum(abs(a-b) for a in xs for b in xs)/(2*n*total)),
            'jain':nullable(total*total/(n*squares))}


def evaluate(u, outside, market, values, epsilon_star, marginals, metadata, tolerance):
    n=len(outside);ids=range(1,n+1)
    if set(u)!=set(ids) or any(not math.isfinite(x) for x in u.values()):raise ValueError('Invalid policy allocation')
    # Conservative IEEE-754 summation/subtraction guard, not a model relaxation.
    # At the M6 target boundary, cancellation of annual AUD amounts can exceed
    # 1e-5 by a few ulps. Preserve raw values and expose the exact effective threshold.
    scale=max(1.,max(abs(x) for x in values.values()),sum(abs(x) for x in u.values()))
    roundoff=4*(n+1)*math.ulp(scale)
    classification_tolerance=tolerance+roundoff
    rows,coalition=allocation_diagnostics(values,u,classification_tolerance)
    if abs(coalition['efficiency_residual_aud'])>tolerance:raise ValueError('Inefficient candidate policy')
    bills={i:outside[i]-u[i] for i in ids};total=values[2**n-1];m_sum=sum(marginals.values())
    distance=None if abs(total)<=tolerance or abs(m_sum)<=tolerance else .5*sum(abs(u[i]/total-marginals[i]/m_sum) for i in ids)
    meaningful=distance is not None and total>tolerance and all(u[i]>=0 and marginals[i]/m_sum>=0 for i in ids)
    fidelity=nullable(1-distance) if meaningful else nullable(reason='shares_not_nonnegative_probability_vectors')
    justice={};relative={}
    for i in ids:
        relative[i]=nullable(u[i]/outside[i]) if outside[i]>tolerance else nullable(reason='nonpositive_standalone_cost')
        income=metadata[i].get('annual_income_aud')
        if income is None or not math.isfinite(income) or income<=0:
            justice[i]={'reason':'invalid_positive_income','standalone_energy_burden':None,'policy_energy_burden':None,'energy_burden_change':None,'benefit_as_income_share':None}
        else:
            justice[i]={'reason':None,'standalone_energy_burden':outside[i]/income,'policy_energy_burden':bills[i]/income,
                'energy_burden_change':(bills[i]-outside[i])/income,'benefit_as_income_share':u[i]/income,
                'negative_bill_interpretation':'net annual electricity revenue' if bills[i]<0 else None}
    reasons=[]
    if min(u.values()) < -classification_tolerance:reasons.append('individual_harm')
    proper=max([0.]+[r['deficit_aud'] for r in rows[1:-1]])
    if proper>epsilon_star+classification_tolerance:reasons.append('coalition_deficit_above_least_core')
    return {'benefits_aud':u,'bills_aud':bills,'total_benefit_aud':sum(u.values()),
        'harmed_member_count':sum(x < -classification_tolerance for x in u.values()),
        'classification_tolerance_aud':classification_tolerance,'arithmetic_roundoff_guard_aud':roundoff,
        'constitutionally_admissible':not reasons,'inadmissibility_reasons':reasons,
        'coalition':coalition,'minimum_benefit_aud':min(u.values()),'maximum_benefit_aud':max(u.values()),
        'mean_benefit_aud':sum(u.values())/n,'inequality':inequality(u,tolerance),
        'relative_bill_saving':relative,'market_L1_distance_aud':sum(abs(u[i]-market[i]) for i in ids),
        'equal_benefit_L1_distance_aud':sum(abs(u[i]-total/n) for i in ids),
        'contribution_share_L1_distance':distance,'contribution_fidelity':fidelity,'justice':justice}
