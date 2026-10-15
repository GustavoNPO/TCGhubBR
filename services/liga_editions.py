"""Coleções do TCGdex -> código de edição da Liga Pokémon.

Gerado em 14/10/2026 cruzando o nome em inglês das coleções do TCGdex
(en/sets) com a lista de edições da Liga (?view=cards/edicoes), aceitando
apenas nomes idênticos e sem ambiguidade. As entradas marcadas como
"manual" têm nomes diferentes nas duas fontes e foram conferidas uma a uma.
Coleções novas precisam ser acrescentadas aqui; sem o código, o link da Liga
vira uma busca por nome e é apresentado como não confirmado.
"""

LIGA_EDITIONS = {
    "base1": "BS", "base2": "JU", "basep": "WPR", "base3": "FO", "base4": "B2", "base5": "TR",
    "gym1": "G1", "gym2": "G2", "neo1": "N1", "neo2": "N2", "si1": "SI", "neo3": "N3", "neo4": "N4",
    "lc": "LC", "bog": "BG", "ecard2": "AQ", "ecard3": "SKY",
    "ex1": "RS", "ex2": "SS", "np": "NBSP", "ex3": "DR", "ex4": "MA", "ex5": "HL",
    "tk-ex-latia": "TK1A", "tk-ex-latio": "TK1B", "ex6": "FL", "pop1": "P1", "ex7": "TRR", "ex8": "DX",
    "ex9": "EM", "pop2": "P2", "ex10": "UF", "ex11": "DS", "ex12": "LM", "pop3": "P3", "ex13": "HP",
    "pop4": "P4", "ex14": "CG", "ex15": "DF", "ex16": "PK", "pop5": "P5",
    "dp1": "DP", "dp2": "MT", "pop6": "P6", "dp3": "SW", "dp4": "GE", "pop7": "P7", "dp5": "MD",
    "dp6": "LA", "pop8": "P8", "dp7": "SF", "pl1": "PL", "pop9": "P9", "pl2": "RR", "pl3": "SV", "pl4": "AR",
    "tk-hs-r": "TK4R", "tk-hs-g": "TK4G", "hgss2": "UL", "hgss3": "UD", "hgss4": "TM", "col1": "CL",
    "bw1": "BLW", "2011bw": "MCD1", "bw2": "EPO", "bw3": "NVI", "bw4": "NXD", "bw5": "DEX", "2012bw": "MCD2",
    "bw6": "DRX", "dv1": "DRV", "bw7": "BCR", "bw8": "PLS", "bw9": "PLF", "bw10": "PLB", "bw11": "LTR",
    "xy0": "KSS", "xy1": "XY", "tk-xy-n": "TK6A", "tk-xy-sy": "TK6B", "xy2": "FLF", "2014xy": "MCD14",
    "xy3": "FFI", "xy4": "PHF", "xy5": "PRC", "dc1": "DCR", "tk-xy-latio": "TK8A", "tk-xy-latia": "TK8B",
    "xy6": "ROS", "xy7": "AOR", "xy8": "BKT", "2015xy": "MCD15", "xy9": "BKP", "g1": "GEN",
    "tk-xy-p": "TK9A", "tk-xy-su": "TK9B", "xy10": "FCO", "xy11": "STS", "2016xy": "MCD16", "xy12": "EVO",
    "sm1": "SUM", "sm2": "GRI", "2017sm": "MCD17", "sm3": "BUS", "sm3.5": "SLG", "sm4": "CIN", "sm5": "UPR",
    "sm6": "FLI", "sm7": "CES", "sm7.5": "DRM", "sm8": "LOT", "sm9": "TEU", "det1": "DET", "sm10": "UNB",
    "sm11": "UNM", "sm115": "HIF", "2019sm": "MCD19", "sm12": "CEC",
    "swsh1": "SSH", "swsh2": "RCL", "swsh3": "DAA", "swsh3.5": "CPA", "swsh4": "VIV", "2021swsh": "MC21",
    "swsh4.5": "SHF", "swsh5": "BST", "swsh6": "CRE", "swsh7": "EVS", "cel25cc": "CCC", "cel25": "CEL",
    "swsh8": "FST", "swsh9tg": "BSTG", "swsh9": "BRS", "swsh10": "ASR", "swsh10tg": "ARTG", "swsh10.5": "PGO",
    "2022swsh": "MC22", "swsh11": "LOR", "swsh11tg": "LORTG", "swsh12": "SIT", "swsh12tg": "SITTG",
    "swsh12.5": "CRZ",
    "sv01": "SV1", "sv02": "PAL", "2023sv": "M23", "sv03": "OBF", "sv03.5": "MEW", "sv04": "PAR",
    "sv04.5": "PAF", "sv05": "TEF", "sv06": "TWM", "sv06.5": "SFA", "sv07": "SCR", "sv08": "SSP",
    "sv08.5": "PRE", "sv09": "JTG", "sv10": "DRI", "sv10.5b": "BLK", "sv10.5w": "WHT",
    "me01": "MEG", "me02": "PFL", "me02.5": "ASC", "me03": "POR", "me04": "CRI", "me05": "PBL", "30th": "30C",
    # manual: nomes diferentes nas duas fontes.
    "ecard1": "EX", "hgss1": "HS", "ru1": "RU", "2018sm": "MC18E", "fut2020": "FUT20", "2024sv": "M24",
    "swsh4.5sv": "SFS", "swsh12.5gg": "CZGG", "sve": "SV-BE", "mee": "MEEb", "30th-c": "30C-C",
    "tk-ex-m": "TK2M", "tk-ex-p": "TK2P", "tk-dp-l": "TK3B", "tk-dp-m": "TK3A",
    "tk-bw-e": "TK5B", "tk-bw-z": "TK5A", "tk-sm-r": "TK10B", "tk-sm-l": "TK10A",
    "dpp": "DPPR", "hgssp": "HSPR", "bwp": "BWPR", "xyp": "XYPR", "smp": "SMP", "swshp": "SSPR",
    "svp": "SVP", "mep": "MEP",
}

# Promos não têm total impresso; a Liga numera como "085/∞".
LIGA_PROMO_SETS = {"dpp", "hgssp", "bwp", "xyp", "smp", "swshp", "svp", "mep"}