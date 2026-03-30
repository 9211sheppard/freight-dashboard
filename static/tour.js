/* tour.js - Lightweight guided tours for Freight Intelligence */

(function () {
  'use strict';

  function sleep(ms) {
    return new Promise(function (resolve) {
      window.setTimeout(resolve, ms);
    });
  }

  function isVisible(element) {
    if (!element) return false;
    const style = window.getComputedStyle(element);
    return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
  }

  async function waitForElement(selector, timeoutMs) {
    const timeout = timeoutMs || 2500;
    const start = Date.now();

    while (Date.now() - start < timeout) {
      const element = document.querySelector(selector);
      if (element) return element;
      await sleep(100);
    }
    return null;
  }

  async function waitForVisible(selector, timeoutMs) {
    const timeout = timeoutMs || 2500;
    const start = Date.now();

    while (Date.now() - start < timeout) {
      const element = document.querySelector(selector);
      if (element && isVisible(element)) return element;
      await sleep(120);
    }
    return null;
  }

  async function ensureSchedulesFiltersVisible() {
    const filterSection = document.getElementById('filterSection');
    if (filterSection && isVisible(filterSection)) return;

    const originButton = document.querySelector('#originPills .origin-pill');
    if (originButton) {
      originButton.click();
      await sleep(250);
    }

    await waitForElement('#destPills .dest-pill', 2500);

    const destButtons = Array.from(document.querySelectorAll('#destPills .dest-pill'));
    const preferredDest = destButtons.find(function (button) {
      const text = button.textContent.toLowerCase();
      return text.indexOf('data') !== -1 && text.indexOf('no data') === -1;
    }) || destButtons[0];

    if (preferredDest) {
      preferredDest.click();
      await sleep(450);
    }

    await waitForVisible('#filterSection', 3000);
  }

  class GuidedTour {
    constructor(steps, storageKey) {
      this.steps = steps || [];
      this.storageKey = storageKey || '';
      this.currentStep = 0;
      this.overlay = null;
      this.tooltip = null;
      this.highlightedElement = null;
      this.active = false;
    }

    createUi() {
      if (this.overlay && this.tooltip) return;

      this.overlay = document.createElement('div');
      this.overlay.className = 'tour-overlay';

      this.tooltip = document.createElement('div');
      this.tooltip.className = 'tour-tooltip';
      this.tooltip.innerHTML = [
        '<div class="tour-tooltip-header">',
        '  <span class="tour-step-counter"></span>',
        '  <button class="tour-close" type="button">&times;</button>',
        '</div>',
        '<h6 class="tour-title"></h6>',
        '<p class="tour-description"></p>',
        '<div class="tour-footer">',
        '  <button class="btn btn-sm btn-outline-secondary tour-prev" type="button">Back</button>',
        '  <button class="btn btn-sm btn-primary tour-next" type="button">Next</button>',
        '</div>'
      ].join('');

      document.body.appendChild(this.overlay);
      document.body.appendChild(this.tooltip);

      this.tooltip.querySelector('.tour-close').addEventListener('click', this.end.bind(this));
      this.tooltip.querySelector('.tour-prev').addEventListener('click', this.prev.bind(this));
      this.tooltip.querySelector('.tour-next').addEventListener('click', this.next.bind(this));
    }

    resolveElement(step) {
      if (!step || !step.element) return null;
      if (typeof step.element === 'string') return document.querySelector(step.element);
      if (typeof step.element === 'function') return step.element();
      return step.element;
    }

    clearHighlight() {
      if (this.highlightedElement) {
        this.highlightedElement.classList.remove('tour-highlight');
        this.highlightedElement = null;
      }
    }

    async start() {
      if (!this.steps.length) return;
      if (this.active) this.end(false);

      this.active = true;
      this.currentStep = 0;
      this.createUi();
      document.body.classList.add('tour-open');
      requestAnimationFrame(() => {
        this.overlay.classList.add('active');
        this.tooltip.classList.add('active');
      });
      await this.showStep(0);
    }

    async showStep(index) {
      if (!this.active) return;
      if (index < 0 || index >= this.steps.length) return;

      this.currentStep = index;
      const step = this.steps[index];

      if (typeof step.beforeShow === 'function') {
        await step.beforeShow();
      }

      const element = this.resolveElement(step);
      if (!element || !isVisible(element)) {
        if (index < this.steps.length - 1) {
          await this.showStep(index + 1);
        } else {
          this.end();
        }
        return;
      }

      this.clearHighlight();
      element.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
      await sleep(220);

      this.highlightedElement = element;
      element.classList.add('tour-highlight');

      const counter = this.tooltip.querySelector('.tour-step-counter');
      const title = this.tooltip.querySelector('.tour-title');
      const description = this.tooltip.querySelector('.tour-description');
      const prevBtn = this.tooltip.querySelector('.tour-prev');
      const nextBtn = this.tooltip.querySelector('.tour-next');

      counter.textContent = 'Step ' + (index + 1) + ' of ' + this.steps.length;
      title.textContent = step.title || '';
      description.textContent = step.description || '';
      prevBtn.disabled = index === 0;
      nextBtn.textContent = index === this.steps.length - 1 ? 'Finish' : 'Next';

      this.positionTooltip(element, step.position || 'bottom');
    }

    positionTooltip(element, preferredPosition) {
      const gap = 16;
      const margin = 12;
      const rect = element.getBoundingClientRect();
      const tooltipRect = this.tooltip.getBoundingClientRect();
      const width = tooltipRect.width || 320;
      const height = tooltipRect.height || 180;

      const positions = [preferredPosition, 'bottom', 'top', 'right', 'left']
        .filter(function (value, idx, array) {
          return array.indexOf(value) === idx;
        });

      let top = rect.bottom + gap;
      let left = rect.left + (rect.width / 2) - (width / 2);

      positions.some(function (position) {
        let candidateTop = top;
        let candidateLeft = left;

        if (position === 'top') {
          candidateTop = rect.top - height - gap;
          candidateLeft = rect.left + (rect.width / 2) - (width / 2);
        } else if (position === 'bottom') {
          candidateTop = rect.bottom + gap;
          candidateLeft = rect.left + (rect.width / 2) - (width / 2);
        } else if (position === 'left') {
          candidateTop = rect.top + (rect.height / 2) - (height / 2);
          candidateLeft = rect.left - width - gap;
        } else if (position === 'right') {
          candidateTop = rect.top + (rect.height / 2) - (height / 2);
          candidateLeft = rect.right + gap;
        }

        const fitsVertically = candidateTop >= margin && (candidateTop + height) <= (window.innerHeight - margin);
        const fitsHorizontally = candidateLeft >= margin && (candidateLeft + width) <= (window.innerWidth - margin);

        if (fitsVertically && fitsHorizontally) {
          top = candidateTop;
          left = candidateLeft;
          return true;
        }
        return false;
      });

      top = Math.max(margin, Math.min(window.innerHeight - height - margin, top));
      left = Math.max(margin, Math.min(window.innerWidth - width - margin, left));

      this.tooltip.style.top = top + 'px';
      this.tooltip.style.left = left + 'px';
    }

    async next() {
      if (!this.active) return;
      if (this.currentStep >= this.steps.length - 1) {
        this.end();
        return;
      }
      await this.showStep(this.currentStep + 1);
    }

    async prev() {
      if (!this.active || this.currentStep === 0) return;
      await this.showStep(this.currentStep - 1);
    }

    end(markCompleted) {
      const shouldPersist = markCompleted !== false;
      this.active = false;
      this.clearHighlight();
      document.body.classList.remove('tour-open');

      if (this.overlay) this.overlay.remove();
      if (this.tooltip) this.tooltip.remove();

      this.overlay = null;
      this.tooltip = null;

      if (shouldPersist && this.storageKey) {
        window.localStorage.setItem(this.storageKey, '1');
      }
    }
  }

  function getPageConfig(pathname) {
    const configs = {
      '/dashboard': {
        key: 'dashboard',
        steps: [
          {
            element: '#contactsSearchPanel',
            title: 'Search Contacts',
            description: 'Search your agent network by name, country, city, or network.',
            position: 'bottom'
          },
          {
            element: '#importCsvBtn',
            title: 'Import CSV',
            description: 'Import new contact lists from CSV files you receive.',
            position: 'bottom'
          },
          {
            element: '#refreshBtn',
            title: 'Refresh Data',
            description: 'Re-sync data from all configured CSV sources.',
            position: 'bottom'
          },
          {
            element: '#learnBtn',
            title: 'Learn',
            description: 'Start interactive training sessions to learn the platform.',
            position: 'bottom'
          },
          {
            element: '#tabNavStrip',
            title: 'Navigate the Platform',
            description: 'Navigate between Contacts, Schedules, Rates, Outreach, and Agents.',
            position: 'bottom'
          },
          {
            element: '#dashboardStats',
            title: 'Stats Cards',
            description: 'See your network at a glance: total contacts, countries, and networks.',
            position: 'bottom'
          }
        ]
      },
      '/schedules': {
        key: 'schedules',
        steps: [
          {
            element: '#originPills',
            title: 'Choose an Origin',
            description: 'Select where shipments are coming from.',
            position: 'bottom'
          },
          {
            element: '#schedStats',
            title: 'Schedule Stats',
            description: 'See total sailings, active carriers, and data coverage.',
            position: 'bottom'
          },
          {
            element: '#filterSection',
            title: 'Refine Results',
            description: 'Filter by carrier or search for specific vessels.',
            position: 'bottom',
            beforeShow: ensureSchedulesFiltersVisible
          }
        ]
      }
    };

    return configs[pathname] || null;
  }

  function initTours() {
    const pathname = window.location.pathname.replace(/\/+$/, '') || '/';
    const config = getPageConfig(pathname);
    const startButton = document.getElementById('startTourBtn');

    if (!config) {
      if (startButton) {
        startButton.disabled = true;
        startButton.title = 'No guided tour is available for this page yet';
      }
      return;
    }

    const storageKey = 'tour_completed_' + config.key;
    const tour = new GuidedTour(config.steps, storageKey);

    if (startButton) {
      startButton.addEventListener('click', function () {
        tour.start();
      });
    }

    window.addEventListener('resize', function () {
      if (tour.active && tour.highlightedElement) {
        tour.positionTooltip(tour.highlightedElement, config.steps[tour.currentStep].position || 'bottom');
      }
    });

    if (!window.localStorage.getItem(storageKey)) {
      window.setTimeout(function () {
        tour.start();
      }, 800);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTours);
  } else {
    initTours();
  }
})();
