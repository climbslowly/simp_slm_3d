function result = analyze_scan(scanDir, parameterFile, outputDir, showBrowser)
% ANALYZE_SCAN 离线单轴扫描，不连接硬件；只依赖 MATLAB 基础功能。
% 输入：扫描目录、与 Python 共用的 JSON 参数、独立输出目录、是否打开滑条浏览器。
% 返回：data [N,24]、radial [N,B]、x_profile [N,Wroi]、y_profile [N,Hroi]。
% ROI 坐标在 JSON 中为零基 [x,y,w,h]；只在矩阵索引时加1。
% 位置是绝对逻辑物镜 mm，planned 是控制器规划位置，不是编码器测量。
if nargin < 4, showBrowser = true; end
scanDir = char(java.io.File(scanDir).getCanonicalPath());
outputDir = char(java.io.File(outputDir).getCanonicalPath());
assert(~strcmpi(scanDir,outputDir) && ~startsWith(lower(outputDir),[lower(scanDir) filesep]), ...
    '输出必须在原始扫描目录之外');
p = jsondecode(fileread(parameterFile));
assert(p.algorithm_version == 1, '不支持的算法版本');
for name = { 'threshold_sigma','candidate_clip_count','radial_bin_px','radial_max_px','preview_stride' }
    v = p.(name{1}); assert(isscalar(v) && isfinite(v) && v>0, '参数必须为有限正数');
end
assert(p.preview_stride==floor(p.preview_stride), '预览步长须为整数');
assert(mod(p.radial_max_px,p.radial_bin_px)==0, '径向范围须为步长整数倍');
assert(numel(p.display_counts)==2 && all(isfinite(p.display_counts)) && p.display_counts(2)>p.display_counts(1));
cfg = jsondecode(fileread(fullfile(scanDir,'scan_config.json')));
assert(cfg.schema_version==1 && any(strcmp(cfg.scan_type,{'AXIS_RANGE','AXIS_LIST'})), '仅支持 schema 1 单轴扫描');
logs = readtable(fullfile(scanDir,'scan_log.csv'),'TextType','string','VariableNamingRule','preserve');
points = cfg.points;
[~,ix] = sort([points.order_index]); points = points(ix);
ids = [points.point_id];
assert(numel(unique(ids))==numel(ids) && numel(unique([points.order_index]))==numel(ids), '计划索引重复');
assert(numel(unique(logs.point_id))==height(logs) && all(ismember(logs.point_id,ids)), '日志 ID 重复或计划外 ID');
columns = {'point_id','order_index','target_x_mm','target_y_mm','target_z_mm', ...
    'planned_x_mm','planned_y_mm','planned_z_mm','image_min','image_max','candidate_clip_pixels', ...
    'acquisition_roi_mean','background_mean','background_std','signal_mean','signal_sum','net_sum', ...
    'threshold_count','centroid_x_px','centroid_y_px','sigma_x_px','sigma_y_px','gradient_energy','threshold_counts'};
n = numel(points); bins = p.radial_max_px/p.radial_bin_px;
data = nan(n,numel(columns)); radial = nan(n,bins);
x_profile = nan(n,p.signal_roi_xywh(3)); y_profile = nan(n,p.signal_roi_xywh(4));
status = repmat("unacquired",n,1); filenames = strings(n,1); sources = strings(n,1);
previews = cell(n,1);
for i = 1:n
    pt = points(i); target = [pt.targets_mm.X pt.targets_mm.Y pt.targets_mm.Z];
    data(i,1:5) = [pt.point_id pt.order_index target];
    j = find(logs.point_id==pt.point_id);
    if isempty(j), continue; end
    row = logs(j,:); status(i) = row.status;
    data(i,6:8) = [row.actual_x_mm row.actual_y_mm row.actual_z_mm];
    filenames(i) = row.filename;
    if ismember('position_source',logs.Properties.VariableNames)
        sources(i) = row.position_source;
    end
    if status(i)~="ok", continue; end
    assert(all(abs(target-[row.target_x_mm row.target_y_mm row.target_z_mm])<=1e-9), 'CSV/JSON 坐标不一致');
    file = safeFile(scanDir,row.filename);
    if ~isfile(file), status(i)="missing_image"; continue; end
    im = imread(file);
    assert(ismatrix(im) && isinteger(im), '需要二维整数灰度 TIFF');
    [data(i,9:end),radial(i,:),x_profile(i,:),y_profile(i,:)] = measureFrame(im,cfg.roi_xywh,p);
    previews{i} = makePreview(im,p.preview_stride);
end
if ~isfolder(outputDir), mkdir(outputDir); end
% 保留原始 JSON 中 null 与 [] 的区别（MATLAB jsondecode 都可能读为空数组）。
parameters_json = fileread(parameterFile); source = scanDir;
% cellstr 用于与 scipy loadmat 的字符串单元数组一致。
status = cellstr(status);
save(fullfile(outputDir,'results.mat'),'data','radial','x_profile','y_profile','columns','status','parameters_json','source','-v7');
t = array2table(data,'VariableNames',columns); t.status = status;
t.filename = filenames; t.position_source = sources;
writetable(t,fullfile(outputDir,'metrics.csv'));
fid = fopen(fullfile(outputDir,'parameters.json'),'w','n','UTF-8');
assert(fid>=0); cleaner = onCleanup(@() fclose(fid)); fprintf(fid,'%s',parameters_json); clear cleaner;
result = struct('data',data,'radial',radial,'x_profile',x_profile,'y_profile',y_profile, ...
    'columns',{columns},'status',{status},'parameters_json',parameters_json,'source',source);
renderFigures(result,previews,cfg,p,outputDir,showBrowser);
fprintf('Offline analysis saved: %s\n',outputDir);
end

function file = safeFile(root,relative)
% 兼容 Windows 相对路径；拒绝越出扫描目录的路径。
file = char(java.io.File(fullfile(root,strrep(char(relative),'\',filesep))).getCanonicalPath());
assert(startsWith(lower(file),[lower(root) filesep]), '图像路径越出扫描目录');
end

function out = crop(im,roi)
% im [H,W]；roi 零基 [x,y,w,h]；out [h,w]，像素值不变。
assert(numel(roi)==4 && all(isfinite(roi)) && all(roi==floor(roi)), 'ROI 必须为整数');
x=roi(1); y=roi(2); w=roi(3); h=roi(4);
assert(x>=0 && y>=0 && w>=2 && h>=2 && x+w<=size(im,2) && y+h<=size(im,1), 'ROI 越界');
out = im(y+1:y+h,x+1:x+w);
end

function out = makePreview(im,stride)
% 与 Python 一致的块均值预览，边缘块按实际像素数平均，不改变原始测量。
[h,w]=size(im); out=zeros(ceil(h/stride),ceil(w/stride));
for dy=1:stride
    for dx=1:stride
        part=double(im(dy:stride:end,dx:stride:end));
        out(1:size(part,1),1:size(part,2))=out(1:size(part,1),1:size(part,2))+part;
    end
end
ny=min(stride,h-(0:stride:h-1)); nx=min(stride,w-(0:stride:w-1));
out=out./(ny'*nx);
end

function [m,radial,xp,yp] = measureFrame(im,acqROI,p)
% 与 Python 完全一致：总体标准差、严格大于阈值、未截断的背景扣除。
% 质心/宽度仅用超过 b+k*std 的像素，权重 I-b；无有效信号时 NaN。
s=double(crop(im,p.signal_roi_xywh)); bg=double(crop(im,p.background_roi_xywh));
b=mean(bg(:)); noise=std(bg(:),1); net=s-b;
threshold=b+p.threshold_sigma*noise; mask=s>threshold;
weights=net; weights(~mask)=0;
r=p.signal_roi_xywh; x=r(1)+(0:r(3)-1); y=r(2)+(0:r(4)-1)';
wx=sum(weights,1); wy=sum(weights,2); total=sum(weights(:));
cx=nan; cy=nan; sx=nan; sy=nan; bins=p.radial_max_px/p.radial_bin_px;
radial=nan(1,bins);
if total>0
    cx=sum(wx.*x)/total; cy=sum(wy.*y)/total;
    sx=sqrt(sum(wx.*(x-cx).^2)/total); sy=sqrt(sum(wy.*(y-cy).^2)/total);
    radius=hypot(y-cy,x-cx); ib=floor(radius/p.radial_bin_px);
    valid=ib<bins;
    % accumarray 索引是1基，因此环带编号加1；配对 net(valid) 保留像素对应关系。
    sums=accumarray(ib(valid)+1,net(valid),[bins 1],@sum,0);
    counts=accumarray(ib(valid)+1,1,[bins 1],@sum,0);
    radial=(sums./counts)';
    complete=min([cx-r(1),r(1)+r(3)-1-cx,cy-r(2),r(2)+r(4)-1-cy]);
    radial((1:bins)*p.radial_bin_px>complete)=nan;
end
dx=diff(s,1,2); dy=diff(s,1,1);
gradient=mean(dx(:).^2)+mean(dy(:).^2);
a=double(crop(im,acqROI));
m=[double(min(im(:))) double(max(im(:))) nnz(im>=p.candidate_clip_count) mean(a(:)) ...
    b noise mean(s(:)) sum(s(:)) sum(net(:)) nnz(mask) cx cy sx sy gradient threshold];
xp=mean(net,1); yp=mean(net,2)';
end

function renderFigures(res,previews,cfg,p,out,showBrowser)
data=res.data; n=size(data,1); axisName=cfg.horizontal_axis;
axisCol=2+find('XYZ'==axisName); [~,order]=sort(data(:,axisCol)); z=data(order,axisCol);
f=figure('Visible','off','Position',[50 50 1500 430*ceil(n/3)]);
for i=1:n
    ax=subplot(ceil(n/3),min(n,3),i,'Parent',f);
    drawImage(ax,i);
end
sgtitle(f,sprintf('Position - camera images | common display [%g, %g] counts\nRed: signal ROI; cyan: acquisition ROI | planned coordinates',p.display_counts));
print(f,fullfile(out,'position_images.png'),'-dpng','-r150'); close(f);
f=figure('Visible','off','Position',[50 50 1400 800]);
groups={[12 13],17,23,[19 20],[21 22],10};
units={'counts','counts (sum)','counts^2 / pixel^2','pixel','pixel','counts'};
for j=1:6
    ax=subplot(2,3,j,'Parent',f); plot(ax,z,data(order,groups{j}),'o-'); grid(ax,'on');
    xlabel(ax,['Absolute objective ' axisName ' / mm']); ylabel(ax,units{j});
    legend(ax,res.columns(groups{j}),'Interpreter','none','FontSize',8);
end
print(f,fullfile(out,'metrics.png'),'-dpng','-r150'); close(f);
f=figure('Visible','off','Position',[50 50 900 500]); ax=axes(f);
radii=((0:size(res.radial,2)-1)+.5)*p.radial_bin_px;
plot(ax,radii,res.radial(order,:)'); grid(ax,'on');
xlabel(ax,'Radius from thresholded centroid / pixel'); ylabel(ax,'Annular mean minus background / counts');
legend(ax,compose('point %d: %.4f mm',data(order,1),z));
print(f,fullfile(out,'radial_profiles.png'),'-dpng','-r150'); close(f);
if showBrowser
    f=figure('Name','Position - camera browser','Position',[50 50 1000 800]);
    ax=axes(f,'Position',[.1 .2 .8 .7]); drawImage(ax,1);
    if n>1
        uicontrol(f,'Style','slider','Min',1,'Max',n,'Value',1,'SliderStep',[1/(n-1) 1/(n-1)], ...
            'Units','normalized','Position',[.2 .05 .6 .04],'Callback',@(s,~) drawImage(ax,round(s.Value)));
    end
end
    function drawImage(ax,i)
        cla(ax);
        if ~isempty(previews{i})
            shape=cfg.camera_info.shape;
            imagesc(ax,[0 shape(2)-1],[0 shape(1)-1],previews{i},p.display_counts(:)');
            colormap(ax,gray(256)); axis(ax,'image'); set(ax,'YDir','reverse');
            rectangle(ax,'Position',double(p.signal_roi_xywh(:)')+[-.5 -.5 0 0],'EdgeColor',[1 .39 .28]);
            rectangle(ax,'Position',double(cfg.roi_xywh(:)')+[-.5 -.5 0 0],'EdgeColor','cyan');
        end
        title(ax,sprintf('point %d | %s=%.4f mm\nXYZ=(%.4f, %.4f, %.4f) | %s', ...
            data(i,1),axisName,data(i,axisCol),data(i,3:5),res.status{i}),'FontSize',9);
        xlabel(ax,'x / pixel (zero-based)'); ylabel(ax,'y / pixel');
    end
end
