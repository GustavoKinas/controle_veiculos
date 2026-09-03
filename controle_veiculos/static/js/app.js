/*
 * Comportamento da estrutura da aplicação.
 *
 * Só entra aqui o que HTML e CSS não resolvem sozinhos. O que é nativo
 * continua nativo: a janela de confirmação do fechamento é um <dialog>, os
 * fechamentos do histórico são <details>, e o menu do usuário também — este
 * arquivo apenas fecha o menu ao clicar fora, que é a única parte que o
 * navegador não faz.
 */
(function () {
  "use strict";

  /* ------------------------------------------------------------------ *
   * Menu lateral em telas estreitas.
   *
   * Acima de 1024px a barra é fixa e o botão fica oculto por CSS; abaixo
   * disso ela vira gaveta sobreposta. O estado mora numa classe do <body>,
   * então CSS e JavaScript concordam sobre uma fonte única de verdade.
   * ------------------------------------------------------------------ */
  var corpo = document.body;
  var botaoMenu = document.getElementById("btn-menu");
  var overlay = document.getElementById("nav-overlay");
  var sidebar = document.getElementById("sidebar");

  function abrirMenu() {
    corpo.classList.add("nav-aberta");
    botaoMenu.setAttribute("aria-expanded", "true");
    // Foco vai para a barra: quem navega por teclado continua na gaveta,
    // em vez de seguir no conteúdo que está atrás do véu.
    if (sidebar) sidebar.focus();
  }

  function fecharMenu(devolverFoco) {
    corpo.classList.remove("nav-aberta");
    if (!botaoMenu) return;
    botaoMenu.setAttribute("aria-expanded", "false");
    if (devolverFoco) botaoMenu.focus();
  }

  if (botaoMenu) {
    botaoMenu.addEventListener("click", function () {
      if (corpo.classList.contains("nav-aberta")) fecharMenu(true);
      else abrirMenu();
    });
  }

  if (overlay) {
    overlay.addEventListener("click", function () {
      fecharMenu(true);
    });
  }

  // Navegar fecha a gaveta: sem isto ela fica aberta sobre a página nova.
  if (sidebar) {
    sidebar.addEventListener("click", function (evento) {
      if (evento.target.closest("a")) fecharMenu(false);
    });
  }

  /* ------------------------------------------------------------------ *
   * Escape fecha o que estiver aberto: gaveta e menu do usuário.
   * O <dialog> nativo já trata Escape sozinho.
   * ------------------------------------------------------------------ */
  document.addEventListener("keydown", function (evento) {
    if (evento.key !== "Escape") return;

    if (corpo.classList.contains("nav-aberta")) {
      fecharMenu(true);
      return;
    }
    var menuAberto = document.querySelector("details.usuario[open]");
    if (menuAberto) {
      menuAberto.removeAttribute("open");
      var resumo = menuAberto.querySelector("summary");
      if (resumo) resumo.focus();
    }
  });

  /* ------------------------------------------------------------------ *
   * Menu do usuário: fechar ao clicar fora.
   * ------------------------------------------------------------------ */
  document.addEventListener("click", function (evento) {
    var menu = document.querySelector("details.usuario[open]");
    if (menu && !menu.contains(evento.target)) menu.removeAttribute("open");
  });

  /* ------------------------------------------------------------------ *
   * Aviso global de requisição HTMX em andamento.
   *
   * Preserva o comportamento anterior: o indicador aparece em qualquer
   * requisição e some ao terminar.
   * ------------------------------------------------------------------ */
  var carregando = document.getElementById("carregando-global");
  if (carregando) {
    corpo.addEventListener("htmx:beforeRequest", function () {
      carregando.classList.add("htmx-request");
    });
    corpo.addEventListener("htmx:afterRequest", function () {
      carregando.classList.remove("htmx-request");
    });
  }

  /* ------------------------------------------------------------------ *
   * Mensagens do Django: somem depois de alguns segundos.
   *
   * Só as de sucesso e informação. Erro e aviso permanecem até o operador
   * sair da página — são justamente as que ele precisa ler com calma.
   * ------------------------------------------------------------------ */
  var efemeras = document.querySelectorAll(
    ".mensagens .alerta-sucesso, .mensagens .alerta-info"
  );
  Array.prototype.forEach.call(efemeras, function (elemento) {
    window.setTimeout(function () {
      elemento.hidden = true;
    }, 6000);
  });
})();
