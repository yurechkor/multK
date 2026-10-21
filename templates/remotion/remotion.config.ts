import {Config} from '@remotion/cli/config';
Config.setConcurrency(1);
Config.setVideoImageFormat('png');
if (process.env.BROWSER_EXECUTABLE) Config.setBrowserExecutable(process.env.BROWSER_EXECUTABLE);
