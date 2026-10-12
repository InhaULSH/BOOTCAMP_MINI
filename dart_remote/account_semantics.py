"""Exact semantic aliases verified against the current remote database.

Do not equate operations-generated cash (before interest/tax) with net operating
cash flow. Do not equate PPE component sums or disposals with PPE acquisition.
"""
import json
import re

VERSION='account-semantics-v1'
NONSTANDARD='-표준계정코드 미사용-'
CASHFLOW_NAMES=('영업활동현금흐름','영업활동으로 인한 현금흐름','영업활동으로인한현금흐름',
                '영업활동순현금흐름','영업활동 순현금흐름','영업활동 현금흐름')
PPE_IDS={'ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities',
         'ifrs_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities'}
PPE_NAMES={'유형자산의취득','유형자산취득','유형자산의취득으로인한현금유출'}

def clean(value):return re.sub(r'\s+','',value or '')

def array(value):
    if isinstance(value,str):
        try:value=json.loads(value)
        except ValueError:return ()
    return tuple(value) if isinstance(value,list) and all(isinstance(x,str) for x in value) else ()

def capex_signature(row):
    ids=array(row.get('source_account_ids'))
    names=array(row.get('source_account_names'))
    direct=row.get('capex_method')=='direct_account' or row.get('source_kind')=='xml'
    # Unknown codes require a single exact total-account label and direct extraction.
    if direct and len(ids)==1 and (ids[0] in PPE_IDS or
        ids[0]==NONSTANDARD and len(names)==1 and clean(names[0]) in PPE_NAMES):
        return ('PPE_ACQUISITION_TOTAL',)
    return tuple(sorted(ids))
