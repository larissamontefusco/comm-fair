"""Reproducible tables and standard Matplotlib figures from canonical JSON only."""
import csv
import json
from pathlib import Path


def write_csv(path, rows):
    with Path(path).open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n')
        writer.writeheader();writer.writerows(rows)


def generate_reports(directory):
    directory=Path(directory)
    comparison=json.loads((directory/'m7_policy_comparison.json').read_text())
    governance=json.loads((directory/'m7_governance.json').read_text())
    ablation=json.loads((directory/'m7_ablation.json').read_text())
    policies=comparison['policies'];members=[];summary=[]
    for p in policies:
        raw=p['raw'];repair=p['repair_to_constitution'];cr=repair['coalition']
        summary.append({'policy_id':p['policy_id'],'harmed':raw['harmed_member_count'],
            'blocking':raw['coalition']['proper_blocking_count'],
            'worst_proper_deficit_aud':raw['coalition']['worst_proper_coalition']['deficit_aud'],
            'r_IR_aud':repair['individual']['r_IR_aud'],'epsilon_IR_aud':cr['epsilon_IR_aud'],
            'r_CR_aud':cr['r_CR_aud'],'CRP_aud':cr['CRP_aud'],'RSG_aud':cr['RSG_aud'],
            'minimum_benefit_aud':raw['minimum_benefit_aud'],'gini':raw['inequality']['gini']['value'],
            'jain':raw['inequality']['jain']['value'],'market_L1_aud':raw['market_L1_distance_aud'],
            'contribution_share_distance':raw['contribution_share_L1_distance'],
            'admissible':raw['constitutionally_admissible']})
        for i in range(1,10):
            k=str(i);j=raw['justice'][k]
            members.append({'policy_id':p['policy_id'],'member_id':i,'B_i_aud':comparison['B_i_aud'][k],
                'raw_bill_aud':raw['bills_aud'][k],'raw_benefit_aud':raw['benefits_aud'][k],
                'candidate_repair_tau_aud':repair['necessary_candidate_repair_tau_aud'][k],
                'repaired_bill_aud':repair['repaired']['bills_aud'][k],
                'repaired_benefit_aud':repair['repaired']['benefits_aud'][k],
                'relative_bill_saving':raw['relative_bill_saving'][k]['value'],
                'relative_saving_reason':raw['relative_bill_saving'][k]['reason'],
                'standalone_energy_burden':j['standalone_energy_burden'],
                'policy_energy_burden':j['policy_energy_burden'],'energy_burden_change':j['energy_burden_change'],
                'repaired_energy_burden':repair['repaired']['justice'][k]['policy_energy_burden']})
    write_csv(directory/'m7_policy_comparison.csv',summary)
    write_csv(directory/'m7_member_outcomes.csv',members)
    write_csv(directory/'m7_member5_case_study.csv',[x for x in members if x['member_id']==5])
    stages=[]
    for row in ablation['stages']:
        stages.append({'stage':row['stage'],'description':row['description'],
            'community_cost_aud':row.get('community_cost_aud',comparison['C_N_aud']),
            'cooperative_surplus_aud':row.get('cooperative_surplus_aud',comparison['v_N_aud']),
            'r_IR_aud':row.get('r_IR_aud'),'r_CR_aud':row.get('r_CR_aud'),
            'CRP_aud':row.get('CRP_aud'),'RSG_aud':row.get('RSG_aud'),
            'selected_policy':row.get('selected_policy'),
            'not_applicable_reason':row.get('not_applicable_reason','Blank fields do not belong to this stage')})
    write_csv(directory/'m7_ablation.csv',stages)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'svg.hashsalt':'comfair-m7','font.family':'DejaVu Sans','font.size':10})
    selected=['P0_protected_marginal','G1_equal_benefit','G2_contribution_proportional','G3_shapley','G4_nucleolus','maxmin_benefit']
    fig,ax=plt.subplots(figsize=(11,6))
    for pid in selected:
        p=next((p for p in policies if p['policy_id']==pid),None)
        if p:ax.plot(range(1,10),[p['raw']['benefits_aud'][str(i)] for i in range(1,10)],marker='o',label=pid)
    ax.axhline(0,color='black',linewidth=.7);ax.set_xticks(range(1,10));ax.set_xlabel('Member')
    ax.set_ylabel('Annual benefit (AUD)');ax.set_title('Raw allocation policies — same physical surplus')
    ax.legend(loc='upper center',bbox_to_anchor=(.5,-.15),ncol=2,fontsize=8);fig.tight_layout()
    fig.savefig(directory/'m7_member_benefits.png',dpi=150);fig.savefig(directory/'m7_member_benefits.svg',metadata={'Date':None});plt.close(fig)
    candidates=governance['admissible_candidates']
    for view,label,filename in [('market_vs_gini','Benefit Gini','m7_market_vs_gini'),
            ('market_vs_contribution','Contribution-share L1 distance','m7_market_vs_contribution')]:
        fig,ax=plt.subplots(figsize=(12,6));legend=[];groups={}
        for j,c in enumerate(candidates,1):
            row=governance['frontiers'][view][c['policy_id']]
            if row['y'] is None:continue
            # Group visually coincident points only; exact values remain in JSON/CSV.
            key=(round(row['x_market_L1_aud'],3),round(row['y'],5))
            groups.setdefault(key,[]).append(j);legend.append(f'{j}: {c["policy_id"]}')
        label_positions=[]
        x_span=max([1.]+[x for x,_ in groups]);y_span=max([.01]+[y for _,y in groups])
        for (x,y),indices in groups.items():
            nearby=sum(abs(x-a)<.05*x_span and abs(y-b)<.04*y_span for a,b in label_positions)
            label_positions.append((x,y))
            ax.scatter([x],[y],s=36,color='#16709b')
            ax.annotate(','.join(map(str,indices)),(x,y),xytext=(4,6+14*nearby),
                textcoords='offset points',fontsize=8,
                arrowprops={'arrowstyle':'-','linewidth':.5} if nearby else None)
        ax.set_xlim(left=-max(1.,ax.get_xlim()[1]*.02));ax.set_ylim(0,max(y for _,y in groups)*1.18 if groups else 1)
        ax.set_xlabel('Total L1 distance from M4 benefits (AUD)');ax.set_ylabel(label)
        ax.set_title('Admissible candidate allocations — discrete trade-off view')
        fig.text(.64,.88,'\n'.join(legend),va='top',fontsize=8)
        fig.text(.64,.32,'Visually coincident points share a label.\nExact values are retained in JSON/CSV.',fontsize=8)
        fig.tight_layout(rect=(0,0,.63,1))
        fig.savefig(directory/(filename+'.png'),dpi=150)
        fig.savefig(directory/(filename+'.svg'),metadata={'Date':None});plt.close(fig)
