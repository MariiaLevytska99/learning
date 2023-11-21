/**
 *  Block navigation in sidebar
 *
 *  Clicking a block link in the sidebar opens the associated section and block in the content area and scrolls the
 *  block in the view.
 */
(function () {

	'use strict';

	var config = {
		blockLinkSelector: '.sidebar-nav li ul li a',
		selectorPrefix: {
			section: '#collapse-section__',
			block: '#collapse-block__',
			blockAnchor: '#link__'
		}
	};


	function setBlockClickHandler() {
		$(config.blockLinkSelector).click(onClick);
	}


	function onClick(event) {
		var data = event.target.dataset,
			sectionSelector = getSelector(data.sectionId, 'section'),
			blockSelector = getSelector(data.blockId, 'block'),
			blockAnchorSelector = getSelector(data.blockId, 'blockAnchor'),
			sectionJq = $(sectionSelector),
			blockJq = $(blockSelector),
			blockAnchorJq = $(blockAnchorSelector);

		if (isCollapsableShown(sectionJq)) {
			if (isCollapsableShown(blockJq)) {
				scrollBlockIntoView(blockAnchorJq);
			} else {
				showBlockAndScrollIntoView();
			}
		} else {
			sectionJq
				.one('shown.bs.collapse', function () {
					showBlockAndScrollIntoView();
				})
				.collapse('show');
		}

		// -- Helper ------------------------------ //

		function scrollBlockIntoView() {
			blockAnchorJq[0].scrollIntoView();
		}

		function showBlockAndScrollIntoView() {
			blockJq
				.one('shown.bs.collapse', function () {
					scrollBlockIntoView();
				})
				.collapse('show');
		}
	}


	function isCollapsableShown(elJq) {
		return elJq.hasClass('in');
	}


	function getSelector(id, configKey) {
		return config.selectorPrefix[configKey] + id;
	}


	$(document).ready(setBlockClickHandler);

})();
