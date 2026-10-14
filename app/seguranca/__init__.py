"""Acesso ao painel: login, usuários, perfis (telas, ações e escopo de dados) e auditoria.

Peças:
    catalogo.py  telas e ações que um perfil pode liberar (registre aqui telas/ações novas)
    escopo.py    restrição de dados (segmento/vertical, obra, empresa) aplicada nos serviços
    repo.py      tabelas painel.usuario / perfil / auditoria_acesso
    sessao.py    usuário da requisição atual (cache curto), pode(acao), pode_tela(tela)
    web.py       rotas Flask /login, /logout, /trocar-senha e o guarda de todas as requisições
"""
