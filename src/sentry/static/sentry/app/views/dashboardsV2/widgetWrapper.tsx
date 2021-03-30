import styled from '@emotion/styled';
import {motion} from 'framer-motion';

import {Widget} from './types';

const WidgetWrapper = styled(motion.div)<{displayType: Widget['displayType']}>`
  position: relative;
  touch-action: manipulation;

  ${p => {
    switch (p.displayType) {
      case 'big_number':
        return `
          /* 2 and 4 cols */
          grid-area: span 1 / span 1;

          @media (min-width: ${p.theme.breakpoints[3]}) {
            /* 6 and 8 cols */
            grid-area: span 1 / span 2;
          }
        `;
      default:
        return `
          /* 2 cols */
          grid-area: span 1 / span 2;

          @media (min-width: ${p.theme.breakpoints[1]}) {
            /* 4, 6 and 8 cols */
            grid-area: span 2 / span 2;
          }
        `;
    }
  }};
`;

export default WidgetWrapper;
