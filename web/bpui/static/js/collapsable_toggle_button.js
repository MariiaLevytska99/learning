/**
 *  Button handling to toggle collapsable sections and blocks.
 */
(function () {

	'use strict';

	var config = {
		buttonSelector: '#toggleCollapsables',
		collapsableSelector: '.panel-collapse'
	};


	function setClickHandler() {
		$(config.buttonSelector).one('click', function () {
			// Assuring synchronized toggling of button label and collapsable visibility
			window.setTimeout(function () {
				onClick();
				setClickHandler();
			}, 0);
		});
	}


	function onClick() {
		var buttonJq = $(config.buttonSelector),
			buttonData = buttonJq.data();

		// Not utilizing collapse('toggle') because some panels could be expanded already and would
		// be collapsed when user wants to expand all panels.

		if (buttonJq.data('mode') === 'expanded') {
			collapse();
		} else {
			expand();
		}


		function collapse() {
			$(config.collapsableSelector)
				.one('hidden.bs.collapse', function () {
					buttonJq
						.text(buttonData.textExpand)
						.data('mode', 'collapsed');
				})
				.collapse('hide');
		}


		function expand() {
			$(config.collapsableSelector + ':not(".in")')
				.one('shown.bs.collapse', function () {
					buttonJq
						.text(buttonData.textCollapse)
						.data('mode', 'expanded');
				})
				.collapse('show');
		}
	}


	$(document).ready(setClickHandler);

})();
